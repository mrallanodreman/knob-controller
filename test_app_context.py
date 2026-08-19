#!/usr/bin/env python3
import unittest

from app_context import (
    AppContext,
    AppProfile,
    choose_profile,
    parse_xprop_active_window,
    parse_xprop_window,
)


class XpropParsingTests(unittest.TestCase):
    def test_parse_active_window(self):
        self.assertEqual(
            parse_xprop_active_window("_NET_ACTIVE_WINDOW(WINDOW): window id # 0x3e00007\n"),
            "0x3e00007",
        )
        self.assertIsNone(
            parse_xprop_active_window("_NET_ACTIVE_WINDOW(WINDOW): window id # 0x0\n")
        )

    def test_parse_window_class_and_title(self):
        app_id, title = parse_xprop_window(
            'WM_CLASS(STRING) = "Navigator", "firefox"\n'
            '_NET_WM_NAME(UTF8_STRING) = "KNOBController — Mozilla Firefox"\n'
        )
        self.assertEqual(app_id, "firefox")
        self.assertEqual(title, "KNOBController — Mozilla Firefox")


class ProfileRoutingTests(unittest.TestCase):
    def setUp(self):
        self.profiles = [
            AppProfile(id="global", name="Global"),
            AppProfile(id="browser", name="Browser", match=("firefox", "chromium")),
            AppProfile(id="media", name="Media", match=("spotify", "vlc")),
        ]

    def test_matches_by_app_id(self):
        context = AppContext(backend="x11", app_id="firefox", title="Docs", available=True)
        self.assertEqual(choose_profile(self.profiles, context), "browser")

    def test_matches_by_title_when_class_is_generic(self):
        context = AppContext(
            backend="x11",
            app_id="electron",
            title="Spotify Premium",
            available=True,
        )
        self.assertEqual(choose_profile(self.profiles, context), "media")

    def test_falls_back_to_global_when_context_unavailable(self):
        context = AppContext(backend="wayland", available=False)
        self.assertEqual(choose_profile(self.profiles, context), "global")

    def test_disabled_profile_does_not_match(self):
        profiles = [
            AppProfile(id="global", name="Global"),
            AppProfile(id="browser", name="Browser", match=("firefox",), enabled=False),
        ]
        context = AppContext(backend="x11", app_id="firefox", available=True)
        self.assertEqual(choose_profile(profiles, context), "global")


if __name__ == "__main__":
    unittest.main()
