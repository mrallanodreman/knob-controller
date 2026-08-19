#!/usr/bin/env python3
import importlib.util
import pathlib
import unittest

MODULE_PATH = pathlib.Path(__file__).with_name('knob-controller-agent.py')
spec = importlib.util.spec_from_file_location('knob_profile_agent', MODULE_PATH)
agent = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(agent)


class ProfileEditorTests(unittest.TestCase):
    def test_slugify(self):
        self.assertEqual(agent.slugify('Premiere Pro / Studio'), 'premiere-pro-studio')

    def test_normalize_profile(self):
        profile = agent.normalize_profile({
            'name': 'Browser Work',
            'match': ['Firefox', 'firefox', '  Chromium  '],
            'mode': 'scroll',
            'gesture_bindings': {'click': 'enter', 'double_click': 'noop', 'long_press': 'esc'},
            'modifier_modes': {'ctrl': 'zoom', 'shift': 'horizontal_scroll', 'alt': 'tabs'},
            'enabled': True,
        })
        self.assertEqual(profile.id, 'browser-work')
        self.assertEqual(profile.match, ('firefox', 'chromium'))
        self.assertEqual(profile.gesture_bindings['click'], 'enter')
        self.assertEqual(profile.modifier_modes['ctrl'], 'zoom')

    def test_rejects_invalid_mode(self):
        with self.assertRaises(ValueError):
            agent.normalize_profile({'name': 'Bad', 'mode': 'timeline'})

    def test_unknown_actions_fall_back_safely(self):
        profile = agent.normalize_profile({
            'name': 'Safe',
            'gesture_bindings': {'click': 'rm-rf'},
            'modifier_modes': {'ctrl': 'warp'},
        })
        self.assertEqual(profile.gesture_bindings['click'], 'noop')
        self.assertEqual(profile.modifier_modes['ctrl'], 'inherit')


if __name__ == '__main__':
    unittest.main()
