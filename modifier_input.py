#!/usr/bin/env python3
"""Modifier-key discovery and state tracking for KNOBController on Linux.

MEETION exposes the knob and the normal keyboard interface as separate evdev
nodes. The knob node is grabbed exclusively by the daemon, while sibling
keyboard nodes are observed non-destructively so Ctrl/Shift/Alt can become
modifier layers without stealing ordinary typing from the desktop session.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
import os
import threading


KEY_LEFTCTRL = 29
KEY_LEFTSHIFT = 42
KEY_LEFTALT = 56
KEY_RIGHTSHIFT = 54
KEY_RIGHTCTRL = 97
KEY_RIGHTALT = 100

MODIFIER_KEY_CODES = {
    KEY_LEFTCTRL: "ctrl",
    KEY_RIGHTCTRL: "ctrl",
    KEY_LEFTSHIFT: "shift",
    KEY_RIGHTSHIFT: "shift",
    KEY_LEFTALT: "alt",
    KEY_RIGHTALT: "alt",
}


@dataclass(frozen=True)
class InputDeviceBlock:
    name: str
    handlers: tuple[str, ...]
    rel: str = ""
    key: str = ""

    @property
    def event_paths(self) -> tuple[str, ...]:
        return tuple(
            "/dev/input/" + handler
            for handler in self.handlers
            if handler.startswith("event")
        )


def parse_input_devices(text: str) -> list[InputDeviceBlock]:
    blocks: list[InputDeviceBlock] = []
    for raw in text.strip().split("\n\n"):
        name = ""
        handlers: tuple[str, ...] = ()
        rel = ""
        key = ""
        for line in raw.splitlines():
            if line.startswith("N: Name="):
                value = line.split("=", 1)[1].strip()
                name = value.strip('"')
            elif line.startswith("H: Handlers="):
                handlers = tuple(line.split("=", 1)[1].split())
            elif line.startswith("B: REL="):
                rel = line.split("=", 1)[1].strip()
            elif line.startswith("B: KEY="):
                key = line.split("=", 1)[1].strip()
        if name and handlers:
            blocks.append(InputDeviceBlock(name=name, handlers=handlers, rel=rel, key=key))
    return blocks


def discover_modifier_devices(
    *,
    device_name: str,
    exclude_path: str | None = None,
    proc_path: Path = Path("/proc/bus/input/devices"),
) -> list[str]:
    """Find sibling evdev nodes that can carry normal keyboard modifiers."""

    blocks = parse_input_devices(proc_path.read_text(encoding="utf-8"))
    result: list[str] = []
    for block in blocks:
        if block.name != device_name:
            continue
        for path in block.event_paths:
            if path == exclude_path:
                continue
            if path not in result:
                result.append(path)
    return result


class ModifierState:
    """Track held Ctrl/Shift/Alt keys across one or more evdev devices."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._pressed_codes: set[int] = set()

    def update(self, code: int, value: int) -> bool:
        """Apply one EV_KEY event. Returns True when it was a modifier event."""

        if code not in MODIFIER_KEY_CODES:
            return False
        with self._lock:
            if value == 0:
                self._pressed_codes.discard(code)
            elif value in {1, 2}:
                self._pressed_codes.add(code)
        return True

    def current(self) -> tuple[str, ...]:
        with self._lock:
            names = {MODIFIER_KEY_CODES[code] for code in self._pressed_codes}
        return tuple(sorted(names))

    def clear(self) -> None:
        with self._lock:
            self._pressed_codes.clear()


class ModifierDeviceSet:
    """Own non-blocking read handles for discovered modifier-capable nodes."""

    def __init__(self, paths: Iterable[str]) -> None:
        self.paths = tuple(dict.fromkeys(paths))
        self._fds: dict[int, str] = {}

    def open(self) -> None:
        self.close()
        for path in self.paths:
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            except OSError:
                continue
            self._fds[fd] = path

    @property
    def fds(self) -> tuple[int, ...]:
        return tuple(self._fds.keys())

    @property
    def opened_paths(self) -> tuple[str, ...]:
        return tuple(self._fds.values())

    def close(self) -> None:
        for fd in list(self._fds):
            try:
                os.close(fd)
            except OSError:
                pass
        self._fds.clear()
