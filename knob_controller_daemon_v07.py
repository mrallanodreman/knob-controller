#!/usr/bin/env python3
"""KNOBController v0.7 interactive device calibration.

Extends v0.6 discovery with a safe calibration workflow for unknown evdev
rotary candidates. Calibrated EV_KEY mappings become persistent adapters and
can be selected by the existing device registry after daemon restart/reconnect.
"""

from __future__ import annotations

import os
import select
import struct
import threading
import time
import uuid
from pathlib import Path

import knob_controller_daemon_v06 as v06
from devices.calibration import CalibrationSession, CapturedEvent
from devices.custom import CalibratedDeviceProfile, upsert_profile

core = v06.core
registry = v06.registry
_session_lock = threading.RLock()
_session: CalibrationSession | None = None
_listener_stop: threading.Event | None = None
_original_get = core.Handler.do_GET
_original_post = core.Handler.do_POST


def _candidate(candidate_id: str):
    for item in v06.discover_devices():
        if item.id == candidate_id:
            return item
    raise ValueError("device candidate not found")


def resolve_source() -> str:
    text = Path("/proc/bus/input/devices").read_text(encoding="utf-8")
    candidates = registry.discover(text)
    v06._last_candidates = candidates
    preferred = registry.preferred(text)
    core.state.device_name = preferred.name

    # Preserve known-good MEETION defaults, or install learned key codes for a
    # calibrated adapter. The proven v0.3 event loop then needs no rewrite.
    if preferred.adapter_id == "calibrated":
        core.KEY_VOLUMEDOWN = int(preferred.metadata["left_code"])
        core.KEY_VOLUMEUP = int(preferred.metadata["right_code"])
        core.KEY_KNOB_CLICK = int(preferred.metadata["press_code"])
        core.DEVICE_NAME = preferred.metadata.get("input_name", preferred.name)
    else:
        core.KEY_VOLUMEDOWN = 114
        core.KEY_VOLUMEUP = 115
        core.KEY_KNOB_CLICK = 113
        core.DEVICE_NAME = "Evision MEETION Keyboard"
    return preferred.event_path


core.resolve_source = resolve_source


def calibration_status() -> dict:
    with _session_lock:
        return {
            "version": "0.7.0",
            "active": _session is not None and not _session.cancelled,
            "session": _session.to_json() if _session is not None else None,
            "steps": ["left", "right", "press"],
            "runtime_decoder": "EV_KEY",
        }


def _listen(session: CalibrationSession, stop_event: threading.Event) -> None:
    fd = None
    try:
        fd = os.open(session.event_path, os.O_RDONLY | os.O_NONBLOCK)
        while not stop_event.is_set() and not session.cancelled and not session.complete:
            ready, _, _ = select.select([fd], [], [], 0.25)
            if not ready:
                continue
            data = os.read(fd, core.EVENT_SIZE * 64)
            usable = len(data) // core.EVENT_SIZE * core.EVENT_SIZE
            for idx in range(0, usable, core.EVENT_SIZE):
                _sec, _usec, ev_type, code, value = struct.unpack(
                    core.EVENT, data[idx : idx + core.EVENT_SIZE]
                )
                if session.record(CapturedEvent(ev_type, code, value)):
                    core.state.publish({"type": "calibration", **calibration_status()})
                    break
    except Exception as exc:
        session.error = str(exc)
        core.state.publish({"type": "calibration", **calibration_status()})
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except Exception:
                pass


def start_calibration(candidate_id: str) -> dict:
    global _session, _listener_stop
    candidate = _candidate(candidate_id)
    if candidate.event_path == core.state.device and core.state.connected:
        raise ValueError("disconnect or select a different candidate before calibrating the active grabbed device")
    with _session_lock:
        if _listener_stop is not None:
            _listener_stop.set()
        _session = CalibrationSession(
            device_id=candidate.id,
            event_path=candidate.event_path,
            device_name=candidate.name,
            vendor_id=candidate.vendor_id,
            product_id=candidate.product_id,
        )
        _listener_stop = threading.Event()
        threading.Thread(target=_listen, args=(_session, _listener_stop), daemon=True).start()
    core.state.publish({"type": "calibration", **calibration_status()})
    return calibration_status()


def save_calibration(name: str | None = None) -> dict:
    global _session
    with _session_lock:
        if _session is None or not _session.complete:
            raise ValueError("calibration is not complete")
        if not _session.runtime_supported:
            raise ValueError("captured device uses an event format not supported by the v0.7 runtime decoder")
        profile = CalibratedDeviceProfile(
            id="custom-" + uuid.uuid4().hex[:12],
            name=(name or _session.device_name or "Calibrated rotary").strip(),
            input_name=_session.device_name,
            vendor_id=_session.vendor_id,
            product_id=_session.product_id,
            left_type=_session.captures["left"].ev_type,
            left_code=_session.captures["left"].code,
            right_type=_session.captures["right"].ev_type,
            right_code=_session.captures["right"].code,
            press_type=_session.captures["press"].ev_type,
            press_code=_session.captures["press"].code,
        )
        upsert_profile(profile)
    core.state.publish({"type": "device_profile_saved", "profile": profile.to_json()})
    return {"saved": True, "profile": profile.to_json(), "restart_required": False}


def patched_get(self):
    if self.path == "/api/calibration":
        self.send_json(calibration_status())
        return
    return _original_get(self)


def patched_post(self):
    global _session, _listener_stop
    if self.path not in {
        "/api/calibration/start",
        "/api/calibration/arm",
        "/api/calibration/cancel",
        "/api/calibration/save",
    }:
        return _original_post(self)
    try:
        length = int(self.headers.get("content-length", "0"))
        import json
        data = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/api/calibration/start":
            self.send_json(start_calibration(str(data.get("device_id") or "")))
            return
        if self.path == "/api/calibration/arm":
            with _session_lock:
                if _session is None:
                    raise ValueError("no calibration session")
                _session.arm(str(data.get("step") or _session.step))
            self.send_json(calibration_status())
            return
        if self.path == "/api/calibration/cancel":
            with _session_lock:
                if _session is not None:
                    _session.cancelled = True
                if _listener_stop is not None:
                    _listener_stop.set()
            self.send_json(calibration_status())
            return
        if self.path == "/api/calibration/save":
            self.send_json(save_calibration(data.get("name")))
            return
    except Exception as exc:
        self.send_json({"error": str(exc)}, 400)


core.Handler.do_GET = patched_get
core.Handler.do_POST = patched_post

# Extend the v0.6 status without modifying the proven core daemon.
_v06_status = core.State.status

def status_v07(self):
    data = _v06_status(self)
    data["version"] = "0.7.0"
    data.setdefault("capabilities", {})["interactive_calibration"] = True
    data["calibration"] = calibration_status()
    return data

core.State.status = status_v07


def main() -> None:
    print("KNOBController v0.7 interactive calibration enabled", flush=True)
    core.main()


if __name__ == "__main__":
    main()
