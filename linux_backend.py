#!/usr/bin/env python3
"""Linux execution backend for KNOBController.

The backend translates platform-agnostic actions from ``knob_engine`` into
Linux uinput events. It deliberately contains no gesture/profile policy.

v0.3 adds horizontal scrolling and key-combo actions so modifier layers can
perform useful contextual controls such as browser zoom and tab switching.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Iterable

from knob_engine import (
    ACTION_HORIZONTAL_SCROLL,
    ACTION_KEY,
    ACTION_KEY_COMBO,
    ACTION_NOOP,
    ACTION_SCROLL,
    ACTION_VOLUME,
    Action,
    Gesture,
)


@dataclass(frozen=True)
class LinuxKeyMap:
    """Named keys supported by the KNOBController virtual keyboard."""

    keys: Dict[str, int]
    volume_up: int
    volume_down: int

    def resolve(self, name: str) -> int:
        if name not in self.keys:
            raise ValueError(f"unsupported Linux key action: {name}")
        return self.keys[name]

    def resolve_many(self, names: Iterable[str]) -> list[int]:
        return [self.resolve(str(name)) for name in names]


class LinuxActionExecutor:
    """Execute normalized KNOBController actions through uinput handles."""

    def __init__(
        self,
        *,
        keyboard_fd: int,
        mouse_fd: int,
        keymap: LinuxKeyMap,
        emit_key: Callable[[int, int], None],
        emit_scroll: Callable[[int, int], None],
        emit_horizontal_scroll: Callable[[int, int], None] | None = None,
        emit_combo: Callable[[int, list[int]], None] | None = None,
    ) -> None:
        self.keyboard_fd = keyboard_fd
        self.mouse_fd = mouse_fd
        self.keymap = keymap
        self.emit_key = emit_key
        self.emit_scroll = emit_scroll
        self.emit_horizontal_scroll = emit_horizontal_scroll
        self.emit_combo = emit_combo

    def __call__(self, action: Action, gesture: Gesture) -> None:
        if action.type == ACTION_NOOP:
            return

        if action.type == ACTION_SCROLL:
            amount = action.amount or gesture.delta or 1
            self.emit_scroll(self.mouse_fd, amount)
            return

        if action.type == ACTION_HORIZONTAL_SCROLL:
            if self.emit_horizontal_scroll is None:
                raise RuntimeError("horizontal scroll emitter is not configured")
            amount = action.amount or gesture.delta or 1
            self.emit_horizontal_scroll(self.mouse_fd, amount)
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

        if action.type == ACTION_KEY_COMBO:
            if self.emit_combo is None:
                raise RuntimeError("key-combo emitter is not configured")
            if not isinstance(action.value, (list, tuple)) or not action.value:
                raise ValueError("key_combo requires a non-empty key list")
            self.emit_combo(
                self.keyboard_fd,
                self.keymap.resolve_many(action.value),
            )
            return

        raise ValueError(f"unsupported action for Linux backend: {action.type}")
