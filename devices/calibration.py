from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

STEPS = ("left", "right", "press")


@dataclass(frozen=True)
class CapturedEvent:
    ev_type: int
    code: int
    value: int

    def to_json(self) -> dict:
        return {"type": self.ev_type, "code": self.code, "value": self.value}


@dataclass
class CalibrationSession:
    device_id: str
    event_path: str
    device_name: str
    vendor_id: str = ""
    product_id: str = ""
    step: str = "left"
    armed: bool = False
    complete: bool = False
    cancelled: bool = False
    captures: dict[str, CapturedEvent] = field(default_factory=dict)
    error: Optional[str] = None

    def arm(self, step: str) -> None:
        if step not in STEPS:
            raise ValueError("invalid calibration step")
        if self.complete or self.cancelled:
            raise ValueError("calibration session is not active")
        self.step = step
        self.armed = True
        self.error = None

    def record(self, event: CapturedEvent) -> bool:
        if not self.armed or self.complete or self.cancelled:
            return False
        if event.ev_type == 0:
            return False
        # Ignore key releases/repeats while learning. For EV_KEY we capture the
        # physical press. Non-key events are recorded as-is for diagnostics.
        if event.ev_type == 1 and event.value != 1:
            return False
        self.captures[self.step] = event
        self.armed = False
        idx = STEPS.index(self.step)
        if idx + 1 < len(STEPS):
            self.step = STEPS[idx + 1]
        else:
            self.complete = True
        return True

    @property
    def runtime_supported(self) -> bool:
        if not self.complete:
            return False
        return all(self.captures[name].ev_type == 1 for name in STEPS)

    def to_json(self) -> dict:
        return {
            "device_id": self.device_id,
            "event_path": self.event_path,
            "device_name": self.device_name,
            "vendor_id": self.vendor_id,
            "product_id": self.product_id,
            "step": self.step,
            "armed": self.armed,
            "complete": self.complete,
            "cancelled": self.cancelled,
            "runtime_supported": self.runtime_supported,
            "captures": {name: event.to_json() for name, event in self.captures.items()},
            "error": self.error,
        }
