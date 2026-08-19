#!/usr/bin/env python3
"""KNOBController v0.8 calibration UI + EV_REL runtime decoder.

v0.8 keeps the proven hardware/action stack and teaches the runtime to decode
both key-style knobs and relative-axis knobs learned by the calibration flow.
"""

from __future__ import annotations

import fcntl
import os
import select
import struct
import time
import uuid
from pathlib import Path

import knob_controller_daemon_v07 as v07
from devices.custom import CalibratedDeviceProfile, upsert_profile
from devices.decoder import EventSpec, RuntimeEventMap, legacy_meetion_map

core = v07.core
registry = v07.registry
_runtime_map: RuntimeEventMap = legacy_meetion_map(
    left_code=core.KEY_VOLUMEDOWN,
    right_code=core.KEY_VOLUMEUP,
    press_code=core.KEY_KNOB_CLICK,
)


def _map_from_candidate(candidate) -> RuntimeEventMap:
    if candidate.adapter_id != "calibrated":
        return legacy_meetion_map(left_code=114, right_code=115, press_code=113)
    meta = candidate.metadata
    event_map = RuntimeEventMap(
        left=EventSpec(int(meta["left_type"]), int(meta["left_code"]), int(meta["left_value"])),
        right=EventSpec(int(meta["right_type"]), int(meta["right_code"]), int(meta["right_value"])),
        press=EventSpec(int(meta["press_type"]), int(meta["press_code"]), int(meta.get("press_value", "1"))),
    )
    if not event_map.supported:
        raise RuntimeError("calibrated event map is not supported by the v0.8 runtime")
    return event_map


def resolve_source() -> str:
    global _runtime_map
    text = Path("/proc/bus/input/devices").read_text(encoding="utf-8")
    candidates = registry.discover(text)
    v07.v06._last_candidates = candidates
    preferred = registry.preferred(text)
    core.state.device_name = preferred.name
    core.DEVICE_NAME = preferred.metadata.get("input_name", preferred.name)
    _runtime_map = _map_from_candidate(preferred)
    return preferred.event_path


core.resolve_source = resolve_source


def save_calibration(name: str | None = None) -> dict:
    with v07._session_lock:
        session = v07._session
        if session is None or not session.complete:
            raise ValueError("calibration is not complete")
        if not session.runtime_supported:
            raise ValueError("captured mapping is not supported; rotate must be EV_KEY or EV_REL and press must be EV_KEY")
        profile = CalibratedDeviceProfile(
            id="custom-" + uuid.uuid4().hex[:12],
            name=(name or session.device_name or "Calibrated rotary").strip(),
            input_name=session.device_name,
            vendor_id=session.vendor_id,
            product_id=session.product_id,
            left_type=session.captures["left"].ev_type,
            left_code=session.captures["left"].code,
            left_value=session.captures["left"].value,
            right_type=session.captures["right"].ev_type,
            right_code=session.captures["right"].code,
            right_value=session.captures["right"].value,
            press_type=session.captures["press"].ev_type,
            press_code=session.captures["press"].code,
            press_value=session.captures["press"].value,
        )
        upsert_profile(profile)
    core.state.publish({"type": "device_profile_saved", "profile": profile.to_json()})
    return {
        "saved": True,
        "profile": profile.to_json(),
        "restart_required": False,
        "decoder": session.decoder_kind,
    }


v07.save_calibration = save_calibration


def knob_loop() -> None:
    source = None
    mouse = None
    keyboard = None
    gesture_engine = None
    modifier_devices = None
    modifier_state = core.ModifierState()

    while core.state.running:
        try:
            source_path = resolve_source()
            event_map = _runtime_map
            core.state.device = source_path
            core.state.last_error = None
            source = os.open(source_path, os.O_RDONLY | os.O_NONBLOCK)
            mouse, keyboard = core.create_uinput()
            fcntl.ioctl(source, core.EVIOCGRAB, 1)

            modifier_paths = core.discover_modifier_devices(
                device_name=core.DEVICE_NAME,
                exclude_path=source_path,
            )
            modifier_devices = core.ModifierDeviceSet(modifier_paths)
            modifier_devices.open()
            core.state.set_modifier_runtime_state(
                devices=list(modifier_devices.opened_paths),
                active=(),
            )

            linux_executor = core.LinuxActionExecutor(
                keyboard_fd=keyboard,
                mouse_fd=mouse,
                keymap=core.LinuxKeyMap(
                    keys=core.LINUX_KEYS,
                    volume_up=core.KEY_VOLUMEUP,
                    volume_down=core.KEY_VOLUMEDOWN,
                ),
                emit_key=core.emit_key,
                emit_scroll=core.emit_scroll,
                emit_horizontal_scroll=core.emit_horizontal_scroll,
                emit_combo=core.emit_combo,
            )
            action_engine = core.ActionEngine(linux_executor)
            core.state.attach_action_engine(action_engine)

            def on_gesture(gesture) -> None:
                action = action_engine.handle(gesture)
                core.publish_gesture(gesture, action)

            gesture_engine = core.GestureEngine(
                on_gesture,
                double_click_seconds=core.DOUBLE_CLICK_SECONDS,
                long_press_seconds=core.LONG_PRESS_SECONDS,
            )

            core.state.connected = True
            core.state.publish({
                "type": "device",
                "connected": True,
                "device": source_path,
                "device_name": core.state.device_name,
                "decoder": "EV_REL+EV_KEY" if event_map.left.ev_type == 2 else "EV_KEY",
                "modifier_devices": list(modifier_devices.opened_paths),
            })
            print(f"KNOBController v0.8 active: {source_path}", flush=True)

            while core.state.running:
                watched = [source, *modifier_devices.fds]
                ready, _, _ = select.select(watched, [], [], 0.5)
                if not ready:
                    continue
                for ready_fd in ready:
                    if ready_fd != source:
                        core.process_modifier_fd(ready_fd, modifier_state)
                        core.state.set_modifier_runtime_state(active=modifier_state.current())
                        continue

                    data = os.read(source, core.EVENT_SIZE * 64)
                    usable = len(data) // core.EVENT_SIZE * core.EVENT_SIZE
                    for idx in range(0, usable, core.EVENT_SIZE):
                        _sec, _usec, ev_type, code, value = struct.unpack(
                            core.EVENT, data[idx : idx + core.EVENT_SIZE]
                        )
                        decoded = event_map.classify(ev_type, code, value)
                        if decoded is None:
                            continue
                        kind, decoded_value = decoded
                        modifiers = modifier_state.current()
                        if kind == "press":
                            if decoded_value == 1:
                                gesture_engine.button_press(modifiers)
                            elif decoded_value == 0:
                                gesture_engine.button_release(modifiers)
                        elif kind == "left":
                            gesture_engine.rotate(-1, modifiers)
                        elif kind == "right":
                            gesture_engine.rotate(1, modifiers)

        except Exception as exc:
            core.state.connected = False
            core.state.last_error = str(exc)
            core.state.publish({"type": "device", "connected": False, "error": str(exc)})
            print(f"KNOBController v0.8 loop error: {exc}", flush=True)
            time.sleep(2)
        finally:
            core.state.connected = False
            core.state.detach_action_engine()
            modifier_state.clear()
            core.state.set_modifier_runtime_state(devices=[], active=())
            if gesture_engine is not None:
                gesture_engine.close()
                gesture_engine = None
            if modifier_devices is not None:
                modifier_devices.close()
                modifier_devices = None
            for fd, destroy in [(source, False), (mouse, True), (keyboard, True)]:
                if fd is None:
                    continue
                try:
                    if destroy:
                        fcntl.ioctl(fd, core.UI_DEV_DESTROY)
                    else:
                        fcntl.ioctl(fd, core.EVIOCGRAB, 0)
                except Exception:
                    pass
                try:
                    os.close(fd)
                except Exception:
                    pass
            source = mouse = keyboard = None


core.knob_loop = knob_loop

_v07_status = core.State.status


def status_v08(self):
    data = _v07_status(self)
    data["version"] = "0.8.0"
    data.setdefault("capabilities", {})["ev_rel_rotary"] = True
    data["capabilities"]["calibration_ui"] = True
    data["runtime_decoder"] = "EV_REL+EV_KEY" if _runtime_map.left.ev_type == 2 else "EV_KEY"
    return data


core.State.status = status_v08


def main() -> None:
    print("KNOBController v0.8 calibration UI + EV_REL decoder enabled", flush=True)
    core.main()


if __name__ == "__main__":
    main()
