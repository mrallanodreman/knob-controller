import unittest

from devices.generic_hid import GenericHIDAdapter
from devices.meetion import MeetionAdapter
from devices.registry import DeviceRegistry


SAMPLE = '''I: Bus=0003 Vendor=320f Product=5055 Version=0110
N: Name="Evision MEETION Keyboard"
H: Handlers=kbd event7
B: REL=1040
B: KEY=1

I: Bus=0003 Vendor=1234 Product=9999 Version=0110
N: Name="Unknown Rotary HID"
H: Handlers=event9
B: REL=0001
'''


class DeviceDiscoveryTests(unittest.TestCase):
    def test_meetion_adapter_finds_known_knob(self):
        devices = list(MeetionAdapter().discover(SAMPLE))
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0].event_path, "/dev/input/event7")
        self.assertEqual(devices[0].adapter_id, "meetion")

    def test_generic_adapter_surfaces_unknown_relative_device(self):
        devices = list(GenericHIDAdapter().discover(SAMPLE))
        paths = {item.event_path for item in devices}
        self.assertIn("/dev/input/event9", paths)

    def test_registry_deduplicates_and_prefers_known_adapter(self):
        registry = DeviceRegistry([MeetionAdapter(), GenericHIDAdapter()])
        devices = registry.discover(SAMPLE)
        self.assertEqual([item.event_path for item in devices].count("/dev/input/event7"), 1)
        preferred = registry.preferred(SAMPLE)
        self.assertEqual(preferred.adapter_id, "meetion")

    def test_unknown_only_is_not_auto_selected(self):
        unknown = '''I: Bus=0003 Vendor=1234 Product=9999 Version=0110
N: Name="Unknown Rotary HID"
H: Handlers=event9
B: REL=0001
'''
        registry = DeviceRegistry([MeetionAdapter(), GenericHIDAdapter()])
        with self.assertRaises(RuntimeError):
            registry.preferred(unknown)


if __name__ == "__main__":
    unittest.main()
