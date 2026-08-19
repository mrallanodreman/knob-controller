#!/usr/bin/env python3
"""Core action and gesture engine for KNOBController.

This module deliberately contains no Linux-specific evdev/uinput code. It turns
raw rotary/button intent into normalized gestures and then resolves those
through a profile into normalized actions. OS backends execute the actions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping, Optional
import threading
import time


GESTURE_ROTATE_LEFT = "rotate_left"
GESTURE_ROTATE_RIGHT = "rotate_right"
GESTURE_CLICK = "click"
GESTURE_DOUBLE_CLICK = "double_click"
GESTURE_LONG_PRESS = "long_press"

SUPPORTED_GESTURES = {
    GESTURE_ROTATE_LEFT,
    GESTURE_ROTATE_RIGHT,
    GESTURE_CLICK,
    GESTURE_DOUBLE_CLICK,
    GESTURE_LONG_PRESS,
}

ACTION_SCROLL = "scroll"
ACTION_VOLUME = "volume"
ACTION_KEY = "key"
ACTION_NOOP = "noop"

SUPPORTED_ACTION_TYPES = {
    ACTION_SCROLL,
    ACTION_VOLUME,
    ACTION_KEY,
    ACTION_NOOP,
}


@dataclass(frozen=True)
class Gesture:
    name: str
    delta: int = 0
    modifiers: tuple[str, ...] = ()
    timestamp: float = field(default_factory=time.monotonic)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.name not in SUPPORTED_GESTURES:
            raise ValueError(f"unsupported gesture: {self.name}")


@dataclass(frozen=True)
class Action:
    type: str
    value: Any = None
    amount: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.type not in SUPPORTED_ACTION_TYPES:
            raise ValueError(f"unsupported action type: {self.type}")


@dataclass
class Profile:
    id: str
    name: str
    bindings: Dict[str, Action]
    application: Optional[str] = None
    enabled: bool = True

    def resolve(self, gesture: Gesture) -> Action:
        if not self.enabled:
            return Action(ACTION_NOOP)
        return self.bindings.get(gesture.name, Action(ACTION_NOOP))


class ActionEngine:
    """Resolve gestures to actions and dispatch them to a backend executor.

    The executor receives ``(action, gesture)``. Linux, Windows and macOS can
    provide different executors while sharing the same profile/action model.
    """

    def __init__(self, executor: Callable[[Action, Gesture], None]) -> None:
        self._executor = executor
        self._lock = threading.RLock()
        self._profiles: Dict[str, Profile] = {}
        self._active_profile_id = "global"

    def set_profiles(self, profiles: Iterable[Profile]) -> None:
        prepared = {profile.id: profile for profile in profiles}
        if "global" not in prepared:
            raise ValueError("a global profile is required")
        with self._lock:
            self._profiles = prepared
            if self._active_profile_id not in prepared:
                self._active_profile_id = "global"

    def upsert_profile(self, profile: Profile) -> None:
        with self._lock:
            self._profiles[profile.id] = profile

    def set_active_profile(self, profile_id: str) -> None:
        with self._lock:
            if profile_id not in self._profiles:
                raise ValueError(f"unknown profile: {profile_id}")
            self._active_profile_id = profile_id

    @property
    def active_profile_id(self) -> str:
        with self._lock:
            return self._active_profile_id

    def resolve(self, gesture: Gesture) -> Action:
        with self._lock:
            profile = self._profiles.get(self._active_profile_id)
            if profile is None:
                profile = self._profiles.get("global")
            if profile is None:
                return Action(ACTION_NOOP)
            return profile.resolve(gesture)

    def handle(self, gesture: Gesture) -> Action:
        action = self.resolve(gesture)
        if action.type != ACTION_NOOP:
            self._executor(action, gesture)
        return action


class GestureEngine:
    """Convert raw button/rotation events into high-level gestures.

    Rotation is emitted immediately. Click recognition waits for the configured
    double-click window so a second press can become ``double_click``. Holding
    the knob beyond ``long_press_seconds`` emits ``long_press`` instead.
    """

    def __init__(
        self,
        emit: Callable[[Gesture], None],
        *,
        double_click_seconds: float = 0.28,
        long_press_seconds: float = 0.60,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if double_click_seconds <= 0:
            raise ValueError("double_click_seconds must be > 0")
        if long_press_seconds <= 0:
            raise ValueError("long_press_seconds must be > 0")

        self._emit = emit
        self._double_click_seconds = double_click_seconds
        self._long_press_seconds = long_press_seconds
        self._clock = clock
        self._lock = threading.RLock()
        self._pressed_at: Optional[float] = None
        self._pending_click_at: Optional[float] = None
        self._pending_timer: Optional[threading.Timer] = None

    def rotate(self, delta: int, modifiers: Iterable[str] = ()) -> None:
        if delta == 0:
            return
        gesture = Gesture(
            GESTURE_ROTATE_RIGHT if delta > 0 else GESTURE_ROTATE_LEFT,
            delta=delta,
            modifiers=tuple(sorted(set(modifiers))),
            timestamp=self._clock(),
        )
        self._emit(gesture)

    def button_press(self) -> None:
        with self._lock:
            if self._pressed_at is None:
                self._pressed_at = self._clock()

    def button_release(self) -> None:
        now = self._clock()
        with self._lock:
            if self._pressed_at is None:
                return

            duration = now - self._pressed_at
            self._pressed_at = None

            if duration >= self._long_press_seconds:
                self._cancel_pending_click_locked()
                self._emit(Gesture(GESTURE_LONG_PRESS, timestamp=now, metadata={"duration": duration}))
                return

            if self._pending_click_at is not None and now - self._pending_click_at <= self._double_click_seconds:
                self._cancel_pending_click_locked()
                self._emit(Gesture(GESTURE_DOUBLE_CLICK, timestamp=now))
                return

            self._pending_click_at = now
            self._pending_timer = threading.Timer(self._double_click_seconds, self._flush_single_click)
            self._pending_timer.daemon = True
            self._pending_timer.start()

    def flush(self) -> None:
        """Force a pending single click to be emitted immediately."""
        with self._lock:
            pending = self._pending_click_at is not None
            self._cancel_pending_click_locked(clear_timestamp=False)
            if not pending:
                return
            timestamp = self._pending_click_at or self._clock()
            self._pending_click_at = None
        self._emit(Gesture(GESTURE_CLICK, timestamp=timestamp))

    def close(self) -> None:
        with self._lock:
            self._cancel_pending_click_locked()
            self._pressed_at = None

    def _flush_single_click(self) -> None:
        with self._lock:
            if self._pending_click_at is None:
                return
            timestamp = self._pending_click_at
            self._pending_click_at = None
            self._pending_timer = None
        self._emit(Gesture(GESTURE_CLICK, timestamp=timestamp))

    def _cancel_pending_click_locked(self, *, clear_timestamp: bool = True) -> None:
        if self._pending_timer is not None:
            self._pending_timer.cancel()
            self._pending_timer = None
        if clear_timestamp:
            self._pending_click_at = None


def build_legacy_compatible_profile(mode: str, click_key: str) -> Profile:
    """Build the v0.x global profile from the existing mode/click settings.

    This keeps current users compatible while the config schema evolves toward
    arbitrary bindings and per-application profiles.
    """

    if mode not in {"scroll", "volume"}:
        raise ValueError("mode must be scroll or volume")

    rotate_action = Action(ACTION_SCROLL, amount=1) if mode == "scroll" else Action(ACTION_VOLUME, amount=1)
    reverse_action = Action(ACTION_SCROLL, amount=-1) if mode == "scroll" else Action(ACTION_VOLUME, amount=-1)

    return Profile(
        id="global",
        name="Global Default",
        bindings={
            GESTURE_ROTATE_RIGHT: rotate_action,
            GESTURE_ROTATE_LEFT: reverse_action,
            GESTURE_CLICK: Action(ACTION_KEY, value=click_key),
            GESTURE_DOUBLE_CLICK: Action(ACTION_NOOP),
            GESTURE_LONG_PRESS: Action(ACTION_NOOP),
        },
    )
