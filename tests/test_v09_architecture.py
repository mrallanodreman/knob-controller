import tempfile
import unittest
from pathlib import Path

import knob_controller
from knob_controller.calibration import CalibrationManager
from knob_controller.devices import DeviceService


SAMPLE = '''I: Bus=0003 Vendor=320f Product=5055 Version=0110
N: Name="Evision MEETION Keyboard"
H: Handlers=kbd event7
B: REL=1040
B: KEY=1
'''


class V09ArchitectureTests(unittest.TestCase):
    def test_package_version(self):
        self.assertEqual(knob_controller.__version__, "0.9.0")

    def test_device_service_resolves_known_adapter(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "devices"
            path.write_text(SAMPLE, encoding="utf-8")
            service = DeviceService(path)
            preferred = service.resolve_preferred()
            self.assertEqual(preferred.adapter_id, "meetion")
            self.assertEqual(preferred.event_path, "/dev/input/event7")
            self.assertEqual(service.runtime_map.left.ev_type, 1)

    def test_calibration_manager_starts_idle(self):
        manager = CalibrationManager(
            event_struct="llHHi",
            event_size=24,
            candidate_resolver=lambda _id: None,
            publish=lambda _item: None,
        )
        result = manager.status()
        self.assertEqual(result["version"], "0.9.0")
        self.assertFalse(result["active"])
        self.assertIsNone(result["session"])


if __name__ == "__main__":
    unittest.main()
