from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .base import DeviceAdapter, DeviceCandidate
from .linux_input import parse_input_devices

DEFAULT_STORE = Path("/etc/knob-controller/devices.json")


@dataclass(frozen=True)
class CalibratedDeviceProfile:
    id: str
    name: str
    input_name: str
    vendor_id: str
    product_id: str
    left_type: int
    left_code: int
    right_type: int
    right_code: int
    press_type: int
    press_code: int
    enabled: bool = True

    @property
    def runtime_supported(self) -> bool:
        # v0.7 runtime decoder safely supports key-event knobs. REL-axis
        # calibration can be recorded later without pretending it is live.
        return self.left_type == self.right_type == self.press_type == 1

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "input_name": self.input_name,
            "vendor_id": self.vendor_id,
            "product_id": self.product_id,
            "left": {"type": self.left_type, "code": self.left_code},
            "right": {"type": self.right_type, "code": self.right_code},
            "press": {"type": self.press_type, "code": self.press_code},
            "enabled": self.enabled,
            "runtime_supported": self.runtime_supported,
        }

    @classmethod
    def from_json(cls, data: dict) -> "CalibratedDeviceProfile":
        left = data.get("left") or {}
        right = data.get("right") or {}
        press = data.get("press") or {}
        return cls(
            id=str(data.get("id") or "").strip(),
            name=str(data.get("name") or data.get("input_name") or "Custom rotary"),
            input_name=str(data.get("input_name") or ""),
            vendor_id=str(data.get("vendor_id") or "").lower(),
            product_id=str(data.get("product_id") or "").lower(),
            left_type=int(left.get("type", -1)),
            left_code=int(left.get("code", -1)),
            right_type=int(right.get("type", -1)),
            right_code=int(right.get("code", -1)),
            press_type=int(press.get("type", -1)),
            press_code=int(press.get("code", -1)),
            enabled=bool(data.get("enabled", True)),
        )


def load_profiles(path: Path = DEFAULT_STORE) -> list[CalibratedDeviceProfile]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [CalibratedDeviceProfile.from_json(item) for item in data.get("devices", [])]
    except Exception:
        return []


def save_profiles(profiles: list[CalibratedDeviceProfile], path: Path = DEFAULT_STORE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": 1, "devices": [item.to_json() for item in profiles]}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def upsert_profile(profile: CalibratedDeviceProfile, path: Path = DEFAULT_STORE) -> None:
    profiles = load_profiles(path)
    replaced = False
    for idx, item in enumerate(profiles):
        if item.id == profile.id:
            profiles[idx] = profile
            replaced = True
            break
    if not replaced:
        profiles.append(profile)
    save_profiles(profiles, path)


class CalibratedAdapter(DeviceAdapter):
    id = "calibrated"
    priority = 20

    def __init__(self, store_path: Path = DEFAULT_STORE) -> None:
        self.store_path = store_path

    def discover(self, input_devices_text: str) -> Iterable[DeviceCandidate]:
        profiles = [p for p in load_profiles(self.store_path) if p.enabled and p.runtime_supported]
        if not profiles:
            return []
        candidates: list[DeviceCandidate] = []
        for block in parse_input_devices(input_devices_text):
            for profile in profiles:
                if profile.input_name and block.name != profile.input_name:
                    continue
                if profile.vendor_id and block.vendor.lower() != profile.vendor_id:
                    continue
                if profile.product_id and block.product.lower() != profile.product_id:
                    continue
                for event_path in block.event_paths:
                    candidates.append(DeviceCandidate(
                        adapter_id=self.id,
                        id=profile.id,
                        name=profile.name,
                        event_path=event_path,
                        vendor_id=block.vendor,
                        product_id=block.product,
                        capabilities=("rotate", "press", "calibrated"),
                        metadata={
                            "input_name": block.name,
                            "left_code": str(profile.left_code),
                            "right_code": str(profile.right_code),
                            "press_code": str(profile.press_code),
                        },
                    ))
        return candidates
