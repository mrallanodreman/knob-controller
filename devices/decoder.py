from __future__ import annotations

from dataclasses import dataclass

EV_KEY = 1
EV_REL = 2


@dataclass(frozen=True)
class EventSpec:
    ev_type: int
    code: int
    value: int

    @property
    def sign(self) -> int:
        if self.value > 0:
            return 1
        if self.value < 0:
            return -1
        return 0


@dataclass(frozen=True)
class RuntimeEventMap:
    left: EventSpec
    right: EventSpec
    press: EventSpec

    @property
    def supported(self) -> bool:
        if self.press.ev_type != EV_KEY:
            return False

        key_rotation = self.left.ev_type == self.right.ev_type == EV_KEY
        rel_rotation = self.left.ev_type == self.right.ev_type == EV_REL
        if key_rotation:
            return self.left.code != self.right.code
        if rel_rotation:
            if self.left.value == 0 or self.right.value == 0:
                return False
            if self.left.code == self.right.code:
                return self.left.sign != self.right.sign
            return True
        return False

    def classify(self, ev_type: int, code: int, value: int) -> tuple[str, int] | None:
        """Classify one evdev event as left/right/press.

        Rotation EV_KEY mappings fire only on key-down. EV_REL mappings use the
        sign learned during calibration, so accelerated wheel values still map
        to the correct direction. Button repeat events are ignored.
        """
        if ev_type == self.press.ev_type and code == self.press.code:
            if ev_type == EV_KEY and value in (0, 1):
                return ("press", value)

        for name, spec in (("left", self.left), ("right", self.right)):
            if ev_type != spec.ev_type or code != spec.code:
                continue
            if ev_type == EV_KEY:
                if value == 1:
                    return (name, -1 if name == "left" else 1)
                continue
            if ev_type == EV_REL and value != 0 and spec.sign == (1 if value > 0 else -1):
                return (name, -abs(value) if name == "left" else abs(value))
        return None


def legacy_meetion_map(*, left_code: int, right_code: int, press_code: int) -> RuntimeEventMap:
    return RuntimeEventMap(
        left=EventSpec(EV_KEY, left_code, 1),
        right=EventSpec(EV_KEY, right_code, 1),
        press=EventSpec(EV_KEY, press_code, 1),
    )
