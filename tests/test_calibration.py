import unittest

from devices.calibration import CalibrationSession, CapturedEvent
from devices.decoder import EV_KEY, EV_REL


class CalibrationSessionTests(unittest.TestCase):
    def _session(self):
        return CalibrationSession(
            device_id="candidate",
            event_path="/dev/input/event9",
            device_name="Test Rotary",
        )

    def test_ev_rel_rotation_plus_key_press_is_supported(self):
        s = self._session()
        s.arm("left")
        self.assertTrue(s.record(CapturedEvent(EV_REL, 8, -1)))
        s.arm("right")
        self.assertTrue(s.record(CapturedEvent(EV_REL, 8, 1)))
        s.arm("press")
        self.assertTrue(s.record(CapturedEvent(EV_KEY, 113, 1)))
        self.assertTrue(s.complete)
        self.assertTrue(s.runtime_supported)
        self.assertEqual(s.decoder_kind, "EV_REL+EV_KEY")

    def test_press_step_rejects_relative_axis(self):
        s = self._session()
        s.arm("press")
        self.assertFalse(s.record(CapturedEvent(EV_REL, 9, 1)))
        self.assertNotIn("press", s.captures)

    def test_key_release_is_not_learned(self):
        s = self._session()
        s.arm("left")
        self.assertFalse(s.record(CapturedEvent(EV_KEY, 114, 0)))
        self.assertTrue(s.armed)
        self.assertNotIn("left", s.captures)

    def test_same_rel_direction_is_not_runtime_supported(self):
        s = self._session()
        s.arm("left")
        s.record(CapturedEvent(EV_REL, 8, 1))
        s.arm("right")
        s.record(CapturedEvent(EV_REL, 8, 2))
        s.arm("press")
        s.record(CapturedEvent(EV_KEY, 113, 1))
        self.assertTrue(s.complete)
        self.assertFalse(s.runtime_supported)


if __name__ == "__main__":
    unittest.main()
