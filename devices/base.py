from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping


@dataclass(frozen=True)
class DeviceCandidate:
    adapter_id: str
    id: str
    name: str
    event_path: str
    transport: str = "evdev"
    vendor_id: str = ""
    product_id: str = ""
    capabilities: tuple[str, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)

    def to_json(self) -> dict:
        return {
            "adapter_id": self.adapter_id,
            "id": self.id,
            "name": self.name,
            "event_path": self.event_path,
            "transport": self.transport,
            "vendor_id": self.vendor_id,
            "product_id": self.product_id,
            "capabilities": list(self.capabilities),
            "metadata": dict(self.metadata),
        }


class DeviceAdapter(ABC):
    id = "base"
    priority = 100

    @abstractmethod
    def discover(self, input_devices_text: str) -> Iterable[DeviceCandidate]:
        raise NotImplementedError

    def accepts(self, candidate: DeviceCandidate) -> bool:
        return candidate.adapter_id == self.id

    @staticmethod
    def read_linux_input_devices(path: Path = Path("/proc/bus/input/devices")) -> str:
        return path.read_text(encoding="utf-8")
