from __future__ import annotations

from pathlib import Path
from typing import Optional

from devices import default_registry
from devices.decoder import EventSpec, RuntimeEventMap, legacy_meetion_map


class DeviceService:
    """Canonical device discovery and runtime-map resolver."""

    def __init__(self, input_devices_path: Path = Path("/proc/bus/input/devices")) -> None:
        self.input_devices_path = input_devices_path
        self.registry = default_registry()
        self._last_candidates = []
        self._active_candidate = None
        self._runtime_map: RuntimeEventMap = legacy_meetion_map(
            left_code=114,
            right_code=115,
            press_code=113,
        )

    def _read(self) -> str:
        return self.input_devices_path.read_text(encoding="utf-8")

    def discover(self):
        try:
            self._last_candidates = self.registry.discover(self._read())
        except Exception:
            self._last_candidates = []
        return list(self._last_candidates)

    def candidate(self, candidate_id: str):
        for item in self.discover():
            if item.id == candidate_id:
                return item
        raise ValueError("device candidate not found")

    def resolve_preferred(self):
        text = self._read()
        candidates = self.registry.discover(text)
        self._last_candidates = candidates
        preferred = self.registry.preferred(text)
        self._active_candidate = preferred
        self._runtime_map = self._map_for(preferred)
        return preferred

    @property
    def runtime_map(self) -> RuntimeEventMap:
        return self._runtime_map

    @property
    def active_candidate(self):
        return self._active_candidate

    def _map_for(self, candidate) -> RuntimeEventMap:
        if candidate.adapter_id != "calibrated":
            return legacy_meetion_map(left_code=114, right_code=115, press_code=113)
        meta = candidate.metadata
        mapping = RuntimeEventMap(
            left=EventSpec(int(meta["left_type"]), int(meta["left_code"]), int(meta["left_value"])),
            right=EventSpec(int(meta["right_type"]), int(meta["right_code"]), int(meta["right_value"])),
            press=EventSpec(int(meta["press_type"]), int(meta["press_code"]), int(meta.get("press_value", "1"))),
        )
        if not mapping.supported:
            raise RuntimeError("calibrated event map is not supported by the runtime")
        return mapping

    def status(self, *, selected_path: str = "") -> dict:
        candidates = self.discover()
        active_adapter: Optional[str] = None
        for item in candidates:
            if item.event_path == selected_path:
                active_adapter = item.adapter_id
                break
        return {
            "active_adapter": active_adapter,
            "candidates": [item.to_json() for item in candidates],
            "supported_count": sum(1 for item in candidates if item.adapter_id != "generic-hid"),
            "candidate_count": len(candidates),
        }
