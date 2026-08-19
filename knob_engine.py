#!/usr/bin/env python3
"""Core action and gesture engine for KNOBController.

The engine is deliberately platform agnostic. Physical backends normalize input
into :class:`Gesture` objects, profiles resolve gestures into :class:`Action`
objects, and platform backends execute those actions.

v0.3 adds modifier-aware bindings. A profile can now distinguish between a
plain rotation and ``Ctrl + rotate``, ``Shift + rotate`` or ``Alt + rotate``
without teaching the core anything about Linux evdev, Windows Raw HID or macOS
IOKit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, Mapping, Optional
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

MODIFIER_CTRL = "ctrl"
MODIFIER_SHIFT = "shift"
MODIFIER_ALT = "alt"
SUPPORTED_MODIFIERS = {MODIFIER_CTRL, MODIFIER_SHIFT, MODIFIER_ALT}

_MODIFIER_ALIASES = {
    "control": MODIFIER_CTRL,
    "leftctrl": MODIFIER_CTRL,
    "rightctrl": MODIFIER_CTRL,
    "left_ctrl": MODIFIER_CTRL,
    "right_ctrl": MODIFIER_CTRL,
    "ctrl": MODIFIER_CTRL,
    "leftshift": MODIFIER_SHIFT,
    "rightshift": MODIFIER_SHIFT,
    "left_shift": MODIFIER_SHIFT,
    "right_shift": MODIFIER_SHIFT,
    "shift": MODIFIER_SHIFT,
    "leftalt": MODIFIER_ALT,
    "rightalt": MODIFIER_ALT,
    "left_alt": MODIFIER_ALT,
    "right_alt": MODIFIER_ALT,
    "alt": MODIFIER_ALT,
}

ACTION_SCROLL = "scroll"
ACTION_HORIZONTAL_SCROLL = "horizontal_scroll"
ACTION_VOLUME = "volume"
ACTION_KEY = "key"
ACTION_KEY_COMBO = "key_combo"
ACTION_NOOP = "noop"

SUPPORTED_ACTION_TYPES = {
    ACTION_SCROLL,
    ACTION_HORIZONTAL_SCROLL,
    ACTION_VOLUME,
    ACTION_KEY,
    ACTION_KEY_COMBO,
    ACTION_NOOP,
}


def normalize_modifiers(modifiers: Iterable[str] = ()) -> tuple[str, ...]:
    """Return a deterministic, supported modifier tuple.

    Unknown modifiers are rejected instead of silently creating binding keys
    that can never be matched by a platform backend.
    """

    normalized = set()
    for modifier in modifiers:
        key = str(modifier).strip().lower().replace("-", "_")
        canonical = _MODIFIER_ALIASES.get(key)
        if canonical is None:
            raise ValueError(f"unsupported modifier: {modifier}")
        normalized.add(canonical)
    return tuple(sorted(normalized))


def binding_key(name: str, modifiers: Iterable[str] = ()) -> str:
    """Build the canonical profile key for a gesture + modifier layer."""

    if name not in SUPPORTED_GESTURES:
        raise ValueError(f"unsupported gesture: {name}")
    normalized = normalize_modifiers(modifiers)
    if not normalized:
        return name
    return "+".join((*normalized, name))


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
        object.__setattr__(self, "modifiers", normalize_modifiers(self.modifiers))

    @property
    def binding_key(self) -> str:
        return binding_key(self.name, self.modifiers)


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
        """Resolve exact modifier layer first, then fall back to plain gesture.

        Falling back keeps old configurations working. If a user has not
        configured ``ctrl+rotate_right``, Ctrl+knob still performs the current
        plain rotation action rather than becoming dead input.
        """

        if not self.enabled:
            return Action(ACTION_NOOP)
        exact = self.bindings.get(gesture.binding_key)
        if exact is not None:
            return exact
        return self.bindings.get(gesture.name, Action(ACTION_NOOP))


class ActionEngine:
    """Resolve gestures through the active profile and execute the action."""

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
    """Convert raw knob events into normalized high-level gestures."""

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
        self._pressed_modifiers: tuple[str, ...] = ()
        self._pending_click_at: Optional[float] = None
        self._pending_click_modifiers: tuple[str, ...] = ()
        self._pending_timer: Optional[threading.Timer] = None

    def rotate(self, delta: int, modifiers: Iterable[str] = ()) -> None:
        if delta == 0:
            return
        self._emit(
            Gesture(
                GESTURE_ROTATE_RIGHT if delta > 0 else GESTURE_ROTATE_LEFT,
                delta=delta,
                modifiers=normalize_modifiers(modifiers),
                timestamp=self._clock(),
            )
        )

    def button_press(self, modifiers: Iterable[str] = ()) -> None:
        with self._lock:
            if self._pressed_at is None:
                self._pressed_at = self._clock()
                self._pressed_modifiers = normalize_modifiers(modifiers)

    def button_release(self, modifiers: Iterable[str] = ()) -> None:
        now = self._clock()
        release_modifiers = normalize_modifiers(modifiers)
        with self._lock:
            if self._pressed_at is None:
                return

            duration = now - self._pressed_at
            press_modifiers = self._pressed_modifiers
            self._pressed_at = None
            self._pressed_modifiers = ()
            gesture_modifiers = press_modifiers or release_modifiers

            if duration >= self._long_press_seconds:
                self._cancel_pending_click_locked()
                self._emit(
                    Gesture(
                        GESTURE_LONG_PRESS,
                        modifiers=gesture_modifiers,
                        timestamp=now,
                        metadata={"duration": duration},
                    )
                )
                return

            if (
                self._pending_click_at is not None
                and now - self._pending_click_at <= self._double_click_seconds
                and self._pending_click_modifiers == gesture_modifiers
            ):
                self._cancel_pending_click_locked()
                self._emit(
                    Gesture(
                        GESTURE_DOUBLE_CLICK,
                        modifiers=gesture_modifiers,
                        timestamp=now,
                    )
                )
                return

            # Different modifier layers should not accidentally collapse into
            # one double click. Flush the older pending click first.
            if self._pending_click_at is not None:
                pending_at = self._pending_click_at
                pending_modifiers = self._pending_click_modifiers
                self._cancel_pending_click_locked()
                self._emit(
                    Gesture(
                        GESTURE_CLICK,
                        modifiers=pending_modifiers,
                        timestamp=pending_at,
                    )
                )

            self._pending_click_at = now
            self._pending_click_modifiers = gesture_modifiers
            self._pending_timer = threading.Timer(
                self._double_click_seconds,
                self._flush_single_click,
            )
            self._pending_timer.daemon = True
            self._pending_timer.start()

    def flush(self) -> None:
        """Force a pending single click to be emitted immediately."""
        with self._lock:
            if self._pending_click_at is None:
                return
            timestamp = self._pending_click_at
            modifiers = self._pending_click_modifiers
            self._cancel_pending_click_locked()
        self._emit(
            Gesture(
                GESTURE_CLICK,
                modifiers=modifiers,
                timestamp=timestamp,
            )
        )

    def close(self) -> None:
        with self._lock:
            self._cancel_pending_click_locked()
            self._pressed_at = None
            self._pressed_modifiers = ()

    def _flush_single_click(self) -> None:
        with self._lock:
            if self._pending_click_at is None:
                return
            timestamp = self._pending_click_at
            modifiers = self._pending_click_modifiers
            self._pending_click_at = None
            self._pending_click_modifiers = ()
            self._pending_timer = None
        self._emit(
            Gesture(
                GESTURE_CLICK,
                modifiers=modifiers,
                timestamp=timestamp,
            )
        )

    def _cancel_pending_click_locked(self) -> None:
        if self._pending_timer is not None:
            self._pending_timer.cancel()
            self._pending_timer = None
        self._pending_click_at = None
        self._pending_click_modifiers = ()


def build_legacy_compatible_profile(mode: str, click_key: str) -> Profile:
    """Build the v0.x global profile while using the v0.3 engine."""

    if mode not in {"scroll", "volume"}:
        raise ValueError("mode must be scroll or volume")

    rotate_action = (
        Action(ACTION_SCROLL, amount=1)
        if mode == "scroll"
        else Action(ACTION_VOLUME, amount=1)
    )
    reverse_action = (
        Action(ACTION_SCROLL, amount=-1)
        if mode == "scroll"
        else Action(ACTION_VOLUME, amount=-1)
    )

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
