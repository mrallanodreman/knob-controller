#!/usr/bin/env python3
"""KNOBController v0.6 device-aware daemon entrypoint.

This compatibility entrypoint keeps the proven v0.3-v0.5 gesture/action runtime
while routing hardware discovery through the new adapter registry. It is an
incremental migration step: device selection is no longer hard-coded in the
service entrypoint, while the existing Linux event loop remains intact.
"""

from __future__ import annotations

from pathlib import Path

import knob_controller_daemon as core
from devices import default_registry


registry = default_registry()
_last_candidates = []
_original_status = core.State.status
_original_get = core.Handler.do_GET


def discover_devices():
    global _last_candidates
    try:
        text = Path("/proc/bus/input/devices").read_text(encoding="utf-8")
        _last_candidates = registry.discover(text)
    except Exception:
        _last_candidates = []
    return list(_last_candidates)


def resolve_source() -> str:
    text = Path("/proc/bus/input/devices").read_text(encoding="utf-8")
    candidates = registry.discover(text)
    global _last_candidates
    _last_candidates = candidates
    preferred = registry.preferred(text)
    core.state.device_name = preferred.name
    return preferred.event_path


def patched_status(self):
    status = _original_status(self)
    candidates = discover_devices()
    status["version"] = "0.6.0"
    status["device_discovery"] = {
        "active_adapter": next((item.adapter_id for item in candidates if item.event_path == self.device), None),
        "candidates": [item.to_json() for item in candidates],
        "supported_count": sum(1 for item in candidates if item.adapter_id != "generic-hid"),
        "candidate_count": len(candidates),
    }
    status.setdefault("capabilities", {})["device_discovery"] = True
    status["capabilities"]["generic_hid"] = any(item.adapter_id == "generic-hid" for item in candidates)
    return status


def patched_get(self):
    if self.path == "/api/devices":
        candidates = discover_devices()
        self.send_json({
            "version": "0.6.0",
            "devices": [item.to_json() for item in candidates],
            "selected": core.state.device,
            "selection_policy": "known-adapter-first",
        })
        return
    return _original_get(self)


core.resolve_source = resolve_source
core.State.status = patched_status
core.Handler.do_GET = patched_get


def main() -> None:
    print("KNOBController v0.6 device registry enabled", flush=True)
    core.main()


if __name__ == "__main__":
    main()
