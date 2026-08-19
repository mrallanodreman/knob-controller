from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .decoder import EV_KEY, EV_REL, EventSpec, RuntimeEventMap

STEPS = ("left", "right", "press")


@dataclass(frozen=True)
class CapturedEvent:
    ev_type: int
    code: int
    value: int

    def to_json(self) -> dict:
        return {"type": self.ev_type, "code": self.code, "value": self.value}

    def to_spec(self) -> EventSpec:
        return EventSpec(self.ev_type, self.code, self.value)


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

        # Learn key-down for button/key-style knobs. For relative axes, learn a
        # non-zero signed movement so runtime can preserve the direction.
        if event.ev_type == EV_KEY and event.value != 1:
            return False
        if event.ev_type == EV_REL and event.value == 0:
            return False
        if event.ev_type not in (EV_KEY, EV_REL):
            return False

        # Press must remain a key event: REL axes do not carry press/release
        # semantics required for click/double-click/long-press recognition.
        if self.step == "press" and event.ev_type != EV_KEY:
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
    def runtime_map(self) -> RuntimeEventMap | None:
        if not self.complete or not all(name in self.captures for name in STEPS):
            return None
        return RuntimeEventMap(
            left=self.captures["left"].to_spec(),
            right=self.captures["right"].to_spec(),
            press=self.captures["press"].to_spec(),
        )

    @property
    def runtime_supported(self) -> bool:
        event_map = self.runtime_map
        return bool(event_map and event_map.supported)

    @property
    def decoder_kind(self) -> str:
        event_map = self.runtime_map
        if event_map is None:
            return "pending"
        if event_map.left.ev_type == event_map.right.ev_type == EV_REL:
            return "EV_REL+EV_KEY"
        if event_map.left.ev_type == event_map.right.ev_type == EV_KEY:
            return "EV_KEY"
        return "unsupported"

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
            "decoder_kind": self.decoder_kind,
            "captures": {name: event.to_json() for name, event in self.captures.items()},
            "error": self.error,
        }
