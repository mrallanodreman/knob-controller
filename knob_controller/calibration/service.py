from __future__ import annotations

import os
import select
import struct
import threading
import uuid
from dataclasses import dataclass
from typing import Callable, Optional

from devices.calibration import CalibrationSession, CapturedEvent
from devices.custom import CalibratedDeviceProfile, upsert_profile


@dataclass
class CalibrationManager:
    """Own the interactive calibration lifecycle independently of HTTP/UI code."""

    event_struct: str
    event_size: int
    candidate_resolver: Callable[[str], object]
    publish: Callable[[dict], None]

    def __post_init__(self) -> None:
        self._lock = threading.RLock()
        self._session: Optional[CalibrationSession] = None
        self._listener_stop: Optional[threading.Event] = None

    @property
    def session(self) -> Optional[CalibrationSession]:
        with self._lock:
            return self._session

    def status(self) -> dict:
        with self._lock:
            session = self._session
            return {
                "version": "0.9.0",
                "active": bool(session is not None and not session.cancelled and not session.complete),
                "session": session.to_json() if session is not None else None,
                "steps": ["left", "right", "press"],
                "runtime_decoders": ["EV_KEY", "EV_REL+EV_KEY"],
            }

    def _emit(self) -> None:
        self.publish({"type": "calibration", **self.status()})

    def _listen(self, session: CalibrationSession, stop_event: threading.Event) -> None:
        fd = None
        try:
            fd = os.open(session.event_path, os.O_RDONLY | os.O_NONBLOCK)
            while not stop_event.is_set() and not session.cancelled and not session.complete:
                ready, _, _ = select.select([fd], [], [], 0.25)
                if not ready:
                    continue
                data = os.read(fd, self.event_size * 64)
                usable = len(data) // self.event_size * self.event_size
                for idx in range(0, usable, self.event_size):
                    _sec, _usec, ev_type, code, value = struct.unpack(
                        self.event_struct, data[idx : idx + self.event_size]
                    )
                    if session.record(CapturedEvent(ev_type, code, value)):
                        self._emit()
                        break
        except Exception as exc:
            session.error = str(exc)
            self._emit()
        finally:
            if fd is not None:
                try:
                    os.close(fd)
                except Exception:
                    pass

    def start(self, candidate_id: str, *, active_path: str = "", connected: bool = False) -> dict:
        candidate = self.candidate_resolver(candidate_id)
        if connected and getattr(candidate, "event_path", "") == active_path:
            raise ValueError("disconnect or choose a different candidate before calibrating the active grabbed device")
        with self._lock:
            if self._listener_stop is not None:
                self._listener_stop.set()
            self._session = CalibrationSession(
                device_id=candidate.id,
                event_path=candidate.event_path,
                device_name=candidate.name,
                vendor_id=candidate.vendor_id,
                product_id=candidate.product_id,
            )
            self._listener_stop = threading.Event()
            threading.Thread(
                target=self._listen,
                args=(self._session, self._listener_stop),
                daemon=True,
            ).start()
        self._emit()
        return self.status()

    def arm(self, step: str) -> dict:
        with self._lock:
            if self._session is None:
                raise ValueError("no calibration session")
            self._session.arm(step or self._session.step)
        self._emit()
        return self.status()

    def cancel(self) -> dict:
        with self._lock:
            if self._session is not None:
                self._session.cancelled = True
            if self._listener_stop is not None:
                self._listener_stop.set()
        self._emit()
        return self.status()

    def save(self, name: str | None = None) -> dict:
        with self._lock:
            session = self._session
            if session is None or not session.complete:
                raise ValueError("calibration is not complete")
            if not session.runtime_supported:
                raise ValueError("captured mapping is not supported by the runtime")
            left = session.captures["left"]
            right = session.captures["right"]
            press = session.captures["press"]
            profile = CalibratedDeviceProfile(
                id="custom-" + uuid.uuid4().hex[:12],
                name=(name or session.device_name or "Calibrated rotary").strip(),
                input_name=session.device_name,
                vendor_id=session.vendor_id,
                product_id=session.product_id,
                left_type=left.ev_type,
                left_code=left.code,
                left_value=left.value,
                right_type=right.ev_type,
                right_code=right.code,
                right_value=right.value,
                press_type=press.ev_type,
                press_code=press.code,
                press_value=press.value,
            )
            upsert_profile(profile)
        payload = {"type": "device_profile_saved", "profile": profile.to_json()}
        self.publish(payload)
        return {
            "saved": True,
            "profile": profile.to_json(),
            "restart_required": False,
            "decoder": session.decoder_kind,
        }
