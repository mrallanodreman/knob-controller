from __future__ import annotations

from .base import DeviceAdapter, DeviceCandidate
from .linux_input import parse_input_devices


class GenericHIDAdapter(DeviceAdapter):
    """Conservative discovery for unknown rotary-like evdev nodes.

    v0.6 only surfaces candidates; it does not auto-select unknown hardware.
    Known adapters always take priority.
    """

    id = "generic-hid"
    priority = 1000

    def discover(self, input_devices_text: str):
        for block in parse_input_devices(input_devices_text):
            if not block.event_paths or not block.rel:
                continue
            # REL capability is a useful discovery signal, but not proof that the
            # node is a knob. Unknown candidates therefore remain opt-in.
            for event_path in block.event_paths:
                yield DeviceCandidate(
                    adapter_id=self.id,
                    id=f"{self.id}:{block.vendor}:{block.product}:{event_path.rsplit('/', 1)[-1]}",
                    name=block.name or "Unknown HID input",
                    event_path=event_path,
                    vendor_id=block.vendor,
                    product_id=block.product,
                    capabilities=("candidate", "relative-input"),
                    metadata={"rel": block.rel, "bus": block.bus, "confidence": "low"},
                )
