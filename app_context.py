#!/usr/bin/env python3
"""Foreground application detection and profile matching for KNOBController.

This module is intentionally unprivileged and independent from evdev/uinput.
The Linux v0.4 profile agent uses it inside the desktop user session, while the
root daemon remains responsible only for hardware I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
import re
import shutil
import subprocess
from typing import Iterable, Mapping, Optional, Sequence


@dataclass(frozen=True)
class AppContext:
    backend: str
    app_id: str = ""
    title: str = ""
    available: bool = False
    detail: str = ""

    @property
    def searchable_text(self) -> str:
        return " ".join(part for part in (self.app_id, self.title) if part).lower()


@dataclass(frozen=True)
class AppProfile:
    id: str
    name: str
    match: tuple[str, ...] = ()
    mode: Optional[str] = None
    gesture_bindings: Mapping[str, str] = field(default_factory=dict)
    modifier_modes: Mapping[str, str] = field(default_factory=dict)
    enabled: bool = True

    def matches(self, context: AppContext) -> bool:
        if not self.enabled or not self.match or not context.available:
            return False
        haystack = context.searchable_text
        return any(pattern.lower() in haystack for pattern in self.match if pattern)


def choose_profile(
    profiles: Sequence[AppProfile],
    context: AppContext,
    *,
    default_id: str = "global",
) -> str:
    """Return the first enabled matching profile, otherwise ``default_id``."""
    for profile in profiles:
        if profile.id == default_id:
            continue
        if profile.matches(context):
            return profile.id
    return default_id


def parse_xprop_active_window(output: str) -> Optional[str]:
    """Extract an X11 window id from ``xprop -root _NET_ACTIVE_WINDOW``."""
    match = re.search(r"window id #\s*(0x[0-9a-fA-F]+)", output or "")
    if not match:
        return None
    window_id = match.group(1).lower()
    if window_id == "0x0":
        return None
    return window_id


def parse_xprop_window(output: str) -> tuple[str, str]:
    """Return ``(app_id, title)`` from xprop WM_CLASS/_NET_WM_NAME output."""
    app_id = ""
    title = ""
    for line in (output or "").splitlines():
        if line.startswith("WM_CLASS"):
            quoted = re.findall(r'"([^"]*)"', line)
            if quoted:
                # X11 usually returns instance, class. The class is more stable.
                app_id = (quoted[-1] or quoted[0]).strip()
        elif line.startswith("_NET_WM_NAME") or line.startswith("WM_NAME"):
            quoted = re.findall(r'"([^"]*)"', line)
            if quoted and not title:
                title = quoted[-1].strip()
    return app_id, title


class X11ForegroundDetector:
    """Detect the focused X11 app using the standard EWMH active-window hint.

    No Python X11 dependency is required. ``xprop`` is part of the common
    x11-utils package on Linux desktops.
    """

    def __init__(self, *, env: Optional[Mapping[str, str]] = None) -> None:
        self.env = dict(env or os.environ)

    @property
    def supported(self) -> bool:
        session_type = self.env.get("XDG_SESSION_TYPE", "").lower()
        if session_type and session_type != "x11":
            return False
        return bool(self.env.get("DISPLAY")) and shutil.which("xprop") is not None

    def detect(self) -> AppContext:
        session_type = self.env.get("XDG_SESSION_TYPE", "").lower()
        if session_type == "wayland":
            return AppContext(
                backend="wayland",
                available=False,
                detail="Wayland foreground-app backend not implemented yet",
            )
        if not self.env.get("DISPLAY"):
            return AppContext(
                backend="x11",
                available=False,
                detail="DISPLAY is not available in this user session",
            )
        if shutil.which("xprop") is None:
            return AppContext(
                backend="x11",
                available=False,
                detail="xprop is not installed",
            )

        try:
            active = subprocess.run(
                ["xprop", "-root", "_NET_ACTIVE_WINDOW"],
                check=True,
                capture_output=True,
                text=True,
                timeout=1.0,
                env=self.env,
            )
            window_id = parse_xprop_active_window(active.stdout)
            if not window_id:
                return AppContext(
                    backend="x11",
                    available=False,
                    detail="No active X11 window",
                )

            window = subprocess.run(
                [
                    "xprop",
                    "-id",
                    window_id,
                    "WM_CLASS",
                    "_NET_WM_NAME",
                    "WM_NAME",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=1.0,
                env=self.env,
            )
            app_id, title = parse_xprop_window(window.stdout)
            if not app_id and not title:
                return AppContext(
                    backend="x11",
                    available=False,
                    detail=f"No application metadata for {window_id}",
                )
            return AppContext(
                backend="x11",
                app_id=app_id,
                title=title,
                available=True,
                detail=window_id,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return AppContext(
                backend="x11",
                available=False,
                detail=str(exc),
            )
