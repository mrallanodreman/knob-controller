#!/usr/bin/env python3
import unittest

from knob_engine import (
    ACTION_HORIZONTAL_SCROLL,
    ACTION_KEY_COMBO,
    ACTION_SCROLL,
    Action,
    ActionEngine,
    Gesture,
    GESTURE_ROTATE_LEFT,
    GESTURE_ROTATE_RIGHT,
    Profile,
    binding_key,
    normalize_modifiers,
)
from linux_backend import LinuxActionExecutor, LinuxKeyMap
from modifier_input import ModifierState, parse_input_devices


class ModifierBindingTests(unittest.TestCase):
    def test_modifier_normalization_is_stable(self):
        self.assertEqual(normalize_modifiers(["Shift", "CTRL", "shift"]), ("ctrl", "shift"))
        self.assertEqual(binding_key(GESTURE_ROTATE_RIGHT, ["ctrl"]), "ctrl+rotate_right")

    def test_profile_prefers_exact_modifier_binding(self):
        profile = Profile(
            id="global",
            name="Global",
            bindings={
                GESTURE_ROTATE_RIGHT: Action(ACTION_SCROLL, amount=1),
                "ctrl+rotate_right": Action(ACTION_KEY_COMBO, value=["ctrl", "equal"]),
            },
        )
        plain = profile.resolve(Gesture(GESTURE_ROTATE_RIGHT, delta=1))
        modified = profile.resolve(Gesture(GESTURE_ROTATE_RIGHT, delta=1, modifiers=("ctrl",)))
        self.assertEqual(plain.type, ACTION_SCROLL)
        self.assertEqual(modified.type, ACTION_KEY_COMBO)

    def test_profile_falls_back_when_layer_is_unconfigured(self):
        profile = Profile(
            id="global",
            name="Global",
            bindings={GESTURE_ROTATE_LEFT: Action(ACTION_SCROLL, amount=-1)},
        )
        action = profile.resolve(Gesture(GESTURE_ROTATE_LEFT, delta=-1, modifiers=("alt",)))
        self.assertEqual(action.type, ACTION_SCROLL)


class ModifierStateTests(unittest.TestCase):
    def test_tracks_left_and_right_modifiers_without_duplicates(self):
        state = ModifierState()
        self.assertTrue(state.update(29, 1))   # left ctrl
        self.assertTrue(state.update(97, 1))   # right ctrl
        self.assertTrue(state.update(42, 1))   # left shift
        self.assertEqual(state.current(), ("ctrl", "shift"))
        state.update(29, 0)
        self.assertEqual(state.current(), ("ctrl", "shift"))
        state.update(97, 0)
        self.assertEqual(state.current(), ("shift",))

    def test_parse_linux_input_blocks(self):
        text = '''I: Bus=0003 Vendor=1234 Product=0001 Version=0110
N: Name="Evision MEETION Keyboard"
H: Handlers=sysrq kbd event4 leds
B: KEY=1

I: Bus=0003 Vendor=1234 Product=0001 Version=0110
N: Name="Evision MEETION Keyboard"
H: Handlers=kbd event7
B: REL=1040
'''
        blocks = parse_input_devices(text)
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0].event_paths, ("/dev/input/event4",))
        self.assertEqual(blocks[1].event_paths, ("/dev/input/event7",))


class LinuxModifierActionTests(unittest.TestCase):
    def setUp(self):
        self.keys = {
            "ctrl": 29,
            "shift": 42,
            "tab": 15,
            "equal": 13,
            "minus": 12,
            "mute": 113,
        }
        self.key_events = []
        self.scroll_events = []
        self.hscroll_events = []
        self.combo_events = []
        self.executor = LinuxActionExecutor(
            keyboard_fd=10,
            mouse_fd=11,
            keymap=LinuxKeyMap(keys=self.keys, volume_up=115, volume_down=114),
            emit_key=lambda fd, key: self.key_events.append((fd, key)),
            emit_scroll=lambda fd, amount: self.scroll_events.append((fd, amount)),
            emit_horizontal_scroll=lambda fd, amount: self.hscroll_events.append((fd, amount)),
            emit_combo=lambda fd, keys: self.combo_events.append((fd, keys)),
        )

    def test_horizontal_scroll(self):
        self.executor(
            Action(ACTION_HORIZONTAL_SCROLL, amount=-1),
            Gesture(GESTURE_ROTATE_LEFT, delta=-1, modifiers=("shift",)),
        )
        self.assertEqual(self.hscroll_events, [(11, -1)])

    def test_key_combo(self):
        self.executor(
            Action(ACTION_KEY_COMBO, value=["ctrl", "tab"]),
            Gesture(GESTURE_ROTATE_RIGHT, delta=1, modifiers=("alt",)),
        )
        self.assertEqual(self.combo_events, [(10, [29, 15])])


if __name__ == "__main__":
    unittest.main()
