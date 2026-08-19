from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .base import DeviceAdapter, DeviceCandidate
from .generic_hid import GenericHIDAdapter
from .meetion import MeetionAdapter


@dataclass
class DeviceRegistry:
    adapters: list[DeviceAdapter]

    def discover(self, input_devices_text: str) -> list[DeviceCandidate]:
        seen: set[str] = set()
        candidates: list[DeviceCandidate] = []
        for adapter in sorted(self.adapters, key=lambda item: item.priority):
            for candidate in adapter.discover(input_devices_text):
                if candidate.event_path in seen:
                    continue
                seen.add(candidate.event_path)
                candidates.append(candidate)
        return candidates

    def preferred(self, input_devices_text: str) -> DeviceCandidate:
        candidates = self.discover(input_devices_text)
        for candidate in candidates:
            if candidate.adapter_id != "generic-hid":
                return candidate
        raise RuntimeError("no supported rotary device found")


def default_registry() -> DeviceRegistry:
    return DeviceRegistry([MeetionAdapter(), GenericHIDAdapter()])
