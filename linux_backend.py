#!/usr/bin/env python3
"""Linux execution backend for KNOBController.

This module translates normalized actions from ``knob_engine`` into Linux
uinput events. It deliberately contains no gesture/profile policy: the core
engine decides *what* should happen and this backend only decides *how* Linux
performs it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict

from knob_engine import (
    ACTION_KEY,
    ACTION_NOOP,
    ACTION_SCROLL,
    ACTION_VOLUME,
    Action,
    Gesture,
)


@dataclass(frozen=True)
class LinuxKeyMap:
    """Named keys supported by the current Linux virtual keyboard."""

    keys: Dict[str, int]
    volume_up: int
    volume_down: int

    def resolve(self, name: str) -> int:
        if name not in self.keys:
            raise ValueError(f"unsupported Linux key action: {name}")
        return self.keys[name]


class LinuxActionExecutor:
    """Execute normalized KNOBController actions through uinput file handles.

    ``emit_key`` and ``emit_scroll`` are injected so this module remains easy
    to unit-test and does not duplicate the low-level input_event packing code
    already owned by the daemon.
    """

    def __init__(
        self,
        *,
        keyboard_fd: int,
        mouse_fd: int,
        keymap: LinuxKeyMap,
        emit_key: Callable[[int, int], None],
        emit_scroll: Callable[[int, int], None],
    ) -> None:
        self.keyboard_fd = keyboard_fd
        self.mouse_fd = mouse_fd
        self.keymap = keymap
        self.emit_key = emit_key
        self.emit_scroll = emit_scroll

    def __call__(self, action: Action, gesture: Gesture) -> None:
        if action.type == ACTION_NOOP:
            return

        if action.type == ACTION_SCROLL:
            amount = action.amount or gesture.delta or 1
            self.emit_scroll(self.mouse_fd, amount)
            return

        if action.type == ACTION_VOLUME:
            amount = action.amount or gesture.delta or 1
            key = self.keymap.volume_up if amount > 0 else self.keymap.volume_down
            for _ in range(max(1, abs(amount))):
                self.emit_key(self.keyboard_fd, key)
            return

        if action.type == ACTION_KEY:
            self.emit_key(self.keyboard_fd, self.keymap.resolve(str(action.value)))
            return

        raise ValueError(f"unsupported action for Linux backend: {action.type}")
