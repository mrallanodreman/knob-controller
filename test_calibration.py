import tempfile
import unittest
from pathlib import Path

from devices.calibration import CalibrationSession, CapturedEvent
from devices.custom import CalibratedAdapter, CalibratedDeviceProfile, save_profiles


INPUT_SAMPLE = '''I: Bus=0003 Vendor=1234 Product=5678 Version=0111
N: Name="Mystery Knob"
H: Handlers=sysrq kbd event9
B: KEY=7 ff9f207ac14057ff febeffdfffefffff fffffffffffffffe
B: REL=1040
'''


class CalibrationSessionTests(unittest.TestCase):
    def test_key_event_calibration_completes(self):
        s = CalibrationSession("x", "/dev/input/event9", "Mystery Knob", "1234", "5678")
        s.arm("left")
        self.assertTrue(s.record(CapturedEvent(1, 114, 1)))
        self.assertEqual(s.step, "right")
        s.arm("right")
        self.assertTrue(s.record(CapturedEvent(1, 115, 1)))
        s.arm("press")
        self.assertTrue(s.record(CapturedEvent(1, 113, 1)))
        self.assertTrue(s.complete)
        self.assertTrue(s.runtime_supported)

    def test_release_is_ignored(self):
        s = CalibrationSession("x", "/dev/input/event9", "Mystery Knob")
        s.arm("left")
        self.assertFalse(s.record(CapturedEvent(1, 114, 0)))
        self.assertTrue(s.armed)

    def test_rel_capture_is_not_runtime_supported_yet(self):
        s = CalibrationSession("x", "/dev/input/event9", "Mystery Knob")
        for step, event in (
            ("left", CapturedEvent(2, 8, -1)),
            ("right", CapturedEvent(2, 8, 1)),
            ("press", CapturedEvent(1, 113, 1)),
        ):
            s.arm(step)
            self.assertTrue(s.record(event))
        self.assertTrue(s.complete)
        self.assertFalse(s.runtime_supported)


class CustomAdapterTests(unittest.TestCase):
    def test_saved_profile_discovers_matching_device(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "devices.json"
            profile = CalibratedDeviceProfile(
                id="custom-test",
                name="My Knob",
                input_name="Mystery Knob",
                vendor_id="1234",
                product_id="5678",
                left_type=1,
                left_code=114,
                right_type=1,
                right_code=115,
                press_type=1,
                press_code=113,
            )
            save_profiles([profile], path)
            found = list(CalibratedAdapter(path).discover(INPUT_SAMPLE))
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0].adapter_id, "calibrated")
            self.assertEqual(found[0].event_path, "/dev/input/event9")
            self.assertEqual(found[0].metadata["left_code"], "114")


if __name__ == "__main__":
    unittest.main()
