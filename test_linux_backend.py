#!/usr/bin/env python3
import unittest

from knob_engine import Action, Gesture
from knob_engine import ACTION_KEY, ACTION_SCROLL, ACTION_VOLUME
from linux_backend import LinuxActionExecutor, LinuxKeyMap


class LinuxActionExecutorTests(unittest.TestCase):
    def setUp(self):
        self.keys = []
        self.scrolls = []
        self.executor = LinuxActionExecutor(
            keyboard_fd=20,
            mouse_fd=10,
            keymap=LinuxKeyMap(
                keys={
                    "mute": 113,
                    "enter": 28,
                    "playpause": 164,
                },
                volume_up=115,
                volume_down=114,
            ),
            emit_key=lambda fd, key: self.keys.append((fd, key)),
            emit_scroll=lambda fd, amount: self.scrolls.append((fd, amount)),
        )

    def test_scroll_uses_mouse_device(self):
        self.executor(
            Action(ACTION_SCROLL, amount=-1),
            Gesture("rotate_left", delta=-1),
        )
        self.assertEqual(self.scrolls, [(10, -1)])
        self.assertEqual(self.keys, [])

    def test_volume_up_uses_virtual_keyboard(self):
        self.executor(
            Action(ACTION_VOLUME, amount=1),
            Gesture("rotate_right", delta=1),
        )
        self.assertEqual(self.keys, [(20, 115)])

    def test_volume_down_uses_virtual_keyboard(self):
        self.executor(
            Action(ACTION_VOLUME, amount=-1),
            Gesture("rotate_left", delta=-1),
        )
        self.assertEqual(self.keys, [(20, 114)])

    def test_named_key_action(self):
        self.executor(
            Action(ACTION_KEY, value="playpause"),
            Gesture("double_click"),
        )
        self.assertEqual(self.keys, [(20, 164)])

    def test_unknown_named_key_is_rejected(self):
        with self.assertRaises(ValueError):
            self.executor(
                Action(ACTION_KEY, value="not-a-real-action"),
                Gesture("click"),
            )


if __name__ == "__main__":
    unittest.main()
