import time
import unittest

from knob_engine import (
    ACTION_KEY,
    ACTION_NOOP,
    ACTION_SCROLL,
    ACTION_VOLUME,
    GESTURE_CLICK,
    GESTURE_DOUBLE_CLICK,
    GESTURE_LONG_PRESS,
    GESTURE_ROTATE_LEFT,
    GESTURE_ROTATE_RIGHT,
    Action,
    ActionEngine,
    Gesture,
    GestureEngine,
    Profile,
    build_legacy_compatible_profile,
)


class ActionEngineTests(unittest.TestCase):
    def test_global_profile_resolves_actions(self):
        executed = []
        engine = ActionEngine(lambda action, gesture: executed.append((action, gesture)))
        profile = Profile(
            id="global",
            name="Global",
            bindings={GESTURE_ROTATE_RIGHT: Action(ACTION_SCROLL, amount=1)},
        )
        engine.set_profiles([profile])

        action = engine.handle(Gesture(GESTURE_ROTATE_RIGHT, delta=1))

        self.assertEqual(action.type, ACTION_SCROLL)
        self.assertEqual(action.amount, 1)
        self.assertEqual(len(executed), 1)

    def test_noop_is_not_dispatched(self):
        executed = []
        engine = ActionEngine(lambda action, gesture: executed.append((action, gesture)))
        engine.set_profiles([Profile(id="global", name="Global", bindings={})])

        action = engine.handle(Gesture(GESTURE_CLICK))

        self.assertEqual(action.type, ACTION_NOOP)
        self.assertEqual(executed, [])

    def test_profile_switching(self):
        executed = []
        engine = ActionEngine(lambda action, gesture: executed.append(action))
        engine.set_profiles(
            [
                Profile(id="global", name="Global", bindings={GESTURE_ROTATE_RIGHT: Action(ACTION_SCROLL, amount=1)}),
                Profile(id="music", name="Music", bindings={GESTURE_ROTATE_RIGHT: Action(ACTION_VOLUME, amount=1)}),
            ]
        )
        engine.set_active_profile("music")

        action = engine.handle(Gesture(GESTURE_ROTATE_RIGHT, delta=1))

        self.assertEqual(action.type, ACTION_VOLUME)
        self.assertEqual(engine.active_profile_id, "music")

    def test_legacy_profile_keeps_current_behavior(self):
        scroll_profile = build_legacy_compatible_profile("scroll", "mute")
        volume_profile = build_legacy_compatible_profile("volume", "playpause")

        self.assertEqual(scroll_profile.bindings[GESTURE_ROTATE_RIGHT].type, ACTION_SCROLL)
        self.assertEqual(scroll_profile.bindings[GESTURE_ROTATE_LEFT].amount, -1)
        self.assertEqual(scroll_profile.bindings[GESTURE_CLICK].type, ACTION_KEY)
        self.assertEqual(scroll_profile.bindings[GESTURE_CLICK].value, "mute")
        self.assertEqual(volume_profile.bindings[GESTURE_ROTATE_RIGHT].type, ACTION_VOLUME)
        self.assertEqual(volume_profile.bindings[GESTURE_CLICK].value, "playpause")


class GestureEngineTests(unittest.TestCase):
    def test_rotation_is_immediate(self):
        emitted = []
        gestures = GestureEngine(emitted.append)

        gestures.rotate(1)
        gestures.rotate(-1)

        self.assertEqual([item.name for item in emitted], [GESTURE_ROTATE_RIGHT, GESTURE_ROTATE_LEFT])
        self.assertEqual([item.delta for item in emitted], [1, -1])
        gestures.close()

    def test_single_click(self):
        emitted = []
        gestures = GestureEngine(emitted.append, double_click_seconds=0.03, long_press_seconds=0.2)

        gestures.button_press()
        gestures.button_release()
        time.sleep(0.06)

        self.assertEqual([item.name for item in emitted], [GESTURE_CLICK])
        gestures.close()

    def test_double_click_suppresses_single_click(self):
        emitted = []
        gestures = GestureEngine(emitted.append, double_click_seconds=0.08, long_press_seconds=0.3)

        gestures.button_press()
        gestures.button_release()
        time.sleep(0.02)
        gestures.button_press()
        gestures.button_release()
        time.sleep(0.1)

        self.assertEqual([item.name for item in emitted], [GESTURE_DOUBLE_CLICK])
        gestures.close()

    def test_long_press(self):
        emitted = []
        gestures = GestureEngine(emitted.append, double_click_seconds=0.03, long_press_seconds=0.04)

        gestures.button_press()
        time.sleep(0.06)
        gestures.button_release()

        self.assertEqual([item.name for item in emitted], [GESTURE_LONG_PRESS])
        self.assertGreaterEqual(emitted[0].metadata["duration"], 0.04)
        gestures.close()

    def test_modifiers_are_normalized(self):
        emitted = []
        gestures = GestureEngine(emitted.append)

        gestures.rotate(1, modifiers=["ctrl", "shift", "ctrl"])

        self.assertEqual(emitted[0].modifiers, ("ctrl", "shift"))
        gestures.close()


if __name__ == "__main__":
    unittest.main()
