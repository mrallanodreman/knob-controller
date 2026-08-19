from __future__ import annotations

from .base import DeviceAdapter, DeviceCandidate
from .linux_input import parse_input_devices


class MeetionAdapter(DeviceAdapter):
    id = "meetion"
    priority = 10
    device_name = "Evision MEETION Keyboard"

    def discover(self, input_devices_text: str):
        for block in parse_input_devices(input_devices_text):
            if block.name != self.device_name:
                continue
            # Existing known-good knob node advertises REL=1040.
            if block.rel != "1040":
                continue
            for event_path in block.event_paths:
                yield DeviceCandidate(
                    adapter_id=self.id,
                    id=f"{self.id}:{event_path.rsplit('/', 1)[-1]}",
                    name=block.name,
                    event_path=event_path,
                    vendor_id=block.vendor,
                    product_id=block.product,
                    capabilities=("rotate", "click"),
                    metadata={"rel": block.rel, "bus": block.bus},
                )
