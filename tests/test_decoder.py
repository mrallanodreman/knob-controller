import unittest

from devices.decoder import EV_KEY, EV_REL, EventSpec, RuntimeEventMap, legacy_meetion_map


class DecoderTests(unittest.TestCase):
    def test_legacy_key_map(self):
        event_map = legacy_meetion_map(left_code=114, right_code=115, press_code=113)
        self.assertTrue(event_map.supported)
        self.assertEqual(event_map.classify(EV_KEY, 114, 1), ("left", -1))
        self.assertEqual(event_map.classify(EV_KEY, 115, 1), ("right", 1))
        self.assertEqual(event_map.classify(EV_KEY, 113, 1), ("press", 1))
        self.assertEqual(event_map.classify(EV_KEY, 113, 0), ("press", 0))
        self.assertIsNone(event_map.classify(EV_KEY, 114, 0))

    def test_relative_axis_map_uses_learned_sign(self):
        event_map = RuntimeEventMap(
            left=EventSpec(EV_REL, 8, -1),
            right=EventSpec(EV_REL, 8, 1),
            press=EventSpec(EV_KEY, 113, 1),
        )
        self.assertTrue(event_map.supported)
        self.assertEqual(event_map.classify(EV_REL, 8, -4), ("left", -4))
        self.assertEqual(event_map.classify(EV_REL, 8, 7), ("right", 7))
        self.assertIsNone(event_map.classify(EV_REL, 8, 0))

    def test_relative_axis_rejects_same_direction_learning(self):
        event_map = RuntimeEventMap(
            left=EventSpec(EV_REL, 8, 1),
            right=EventSpec(EV_REL, 8, 2),
            press=EventSpec(EV_KEY, 113, 1),
        )
        self.assertFalse(event_map.supported)

    def test_press_must_be_key_event(self):
        event_map = RuntimeEventMap(
            left=EventSpec(EV_REL, 8, -1),
            right=EventSpec(EV_REL, 8, 1),
            press=EventSpec(EV_REL, 9, 1),
        )
        self.assertFalse(event_map.supported)


if __name__ == "__main__":
    unittest.main()
