#!/usr/bin/env python3
"""KNOBController Linux daemon v0.3.

Architecture:
    physical knob -> evdev -> GestureEngine -> ActionEngine -> LinuxActionExecutor -> uinput
                         ^
                         └── sibling keyboard evdev nodes track Ctrl/Shift/Alt

v0.3 keeps every v0.2 behavior and adds real modifier layers:

- Shift + knob -> horizontal scroll (default)
- Ctrl + knob  -> zoom (default)
- Alt + knob   -> tab switching (default, configurable)

Modifier policy lives in the profile; Linux-specific key discovery remains in
this daemon/backend layer so the core engine stays portable.
"""

from __future__ import annotations

import fcntl
import json
import os
import queue
import select
import signal
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, Optional

from knob_engine import (
    ACTION_HORIZONTAL_SCROLL,
    ACTION_KEY,
    ACTION_KEY_COMBO,
    ACTION_NOOP,
    ACTION_SCROLL,
    ACTION_VOLUME,
    Action,
    ActionEngine,
    Gesture,
    GestureEngine,
    GESTURE_CLICK,
    GESTURE_DOUBLE_CLICK,
    GESTURE_LONG_PRESS,
    GESTURE_ROTATE_LEFT,
    GESTURE_ROTATE_RIGHT,
    Profile,
    binding_key,
)
from linux_backend import LinuxActionExecutor, LinuxKeyMap
from modifier_input import ModifierDeviceSet, ModifierState, discover_modifier_devices

HOST = "127.0.0.1"
PORT = 8766
CONFIG_PATH = Path("/etc/knob-controller/config.json")
DEVICE_NAME = "Evision MEETION Keyboard"

EV_SYN = 0
EV_KEY = 1
EV_REL = 2
SYN_REPORT = 0
KEY_VOLUMEDOWN = 114
KEY_VOLUMEUP = 115
KEY_KNOB_CLICK = 113
KEY_LEFTCTRL = 29
KEY_LEFTSHIFT = 42
KEY_LEFTALT = 56
KEY_TAB = 15
KEY_MINUS = 12
KEY_EQUAL = 13
REL_HWHEEL = 6
REL_WHEEL = 8
BUS_USB = 0x03

CLICK_KEYS: Dict[str, int] = {
    "mute": 113,
    "enter": 28,
    "esc": 1,
    "tab": KEY_TAB,
    "space": 57,
    "playpause": 164,
}

LINUX_KEYS: Dict[str, int] = {
    **CLICK_KEYS,
    "ctrl": KEY_LEFTCTRL,
    "shift": KEY_LEFTSHIFT,
    "alt": KEY_LEFTALT,
    "minus": KEY_MINUS,
    "equal": KEY_EQUAL,
}

GESTURE_ACTIONS = {"noop", *CLICK_KEYS.keys()}
BUTTON_GESTURES = {
    GESTURE_CLICK,
    GESTURE_DOUBLE_CLICK,
    GESTURE_LONG_PRESS,
}
MODIFIER_LAYERS = ("ctrl", "shift", "alt")
MODIFIER_MODES = {
    "inherit",
    "scroll",
    "horizontal_scroll",
    "volume",
    "zoom",
    "tabs",
}

DEFAULT_MODE = "scroll"
DEFAULT_GESTURE_BINDINGS = {
    GESTURE_CLICK: "mute",
    GESTURE_DOUBLE_CLICK: "noop",
    GESTURE_LONG_PRESS: "noop",
}
DEFAULT_MODIFIER_MODES = {
    "ctrl": "zoom",
    "shift": "horizontal_scroll",
    "alt": "tabs",
}

DOUBLE_CLICK_SECONDS = 0.28
LONG_PRESS_SECONDS = 0.60

IOC_NRBITS = 8
IOC_TYPEBITS = 8
IOC_SIZEBITS = 14
IOC_NRSHIFT = 0
IOC_TYPESHIFT = IOC_NRSHIFT + IOC_NRBITS
IOC_SIZESHIFT = IOC_TYPESHIFT + IOC_TYPEBITS
IOC_DIRSHIFT = IOC_SIZESHIFT + IOC_SIZEBITS
IOC_NONE = 0
IOC_WRITE = 1


def ioc(direction, type_, nr, size):
    return (
        (direction << IOC_DIRSHIFT)
        | (ord(type_) << IOC_TYPESHIFT)
        | (nr << IOC_NRSHIFT)
        | (size << IOC_SIZESHIFT)
    )


UI_DEV_CREATE = ioc(IOC_NONE, "U", 1, 0)
UI_DEV_DESTROY = ioc(IOC_NONE, "U", 2, 0)
UI_SET_EVBIT = ioc(IOC_WRITE, "U", 100, struct.calcsize("i"))
UI_SET_KEYBIT = ioc(IOC_WRITE, "U", 101, struct.calcsize("i"))
UI_SET_RELBIT = ioc(IOC_WRITE, "U", 102, struct.calcsize("i"))
EVIOCGRAB = ioc(IOC_WRITE, "E", 0x90, struct.calcsize("i"))

EVENT = "llHHi"
EVENT_SIZE = struct.calcsize(EVENT)


class State:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.mode = DEFAULT_MODE
        self.gesture_bindings = dict(DEFAULT_GESTURE_BINDINGS)
        self.modifier_modes = dict(DEFAULT_MODIFIER_MODES)
        self.device = "not found"
        self.device_name = DEVICE_NAME
        self.modifier_devices: list[str] = []
        self.active_modifiers: tuple[str, ...] = ()
        self.clients = []
        self.running = True
        self.connected = False
        self.last_error: Optional[str] = None
        self.action_engine: Optional[ActionEngine] = None

    @property
    def click_key(self) -> str:
        return self.gesture_bindings[GESTURE_CLICK]

    def load(self) -> None:
        if not CONFIG_PATH.exists():
            self.save()
            return

        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception as exc:
            self.last_error = f"config load failed: {exc}"
            self.save()
            return

        mode = data.get("mode", DEFAULT_MODE)
        if mode in {"scroll", "volume"}:
            self.mode = mode

        legacy_click = data.get("click_key")
        if legacy_click in CLICK_KEYS:
            self.gesture_bindings[GESTURE_CLICK] = legacy_click

        mappings = data.get("gesture_bindings", {})
        if isinstance(mappings, dict):
            for gesture in BUTTON_GESTURES:
                action = mappings.get(gesture)
                if action in GESTURE_ACTIONS:
                    self.gesture_bindings[gesture] = action

        modifier_modes = data.get("modifier_modes", {})
        if isinstance(modifier_modes, dict):
            for modifier in MODIFIER_LAYERS:
                mode_name = modifier_modes.get(modifier)
                if mode_name in MODIFIER_MODES:
                    self.modifier_modes[modifier] = mode_name

        self.save()

    def save(self) -> None:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 3,
            "mode": self.mode,
            "click_key": self.gesture_bindings[GESTURE_CLICK],
            "gesture_bindings": dict(self.gesture_bindings),
            "modifier_modes": dict(self.modifier_modes),
        }
        tmp = CONFIG_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, CONFIG_PATH)

    def _rotation_pair(self, mode_name: str) -> tuple[Action, Action]:
        if mode_name == "scroll":
            return Action(ACTION_SCROLL, amount=-1), Action(ACTION_SCROLL, amount=1)
        if mode_name == "horizontal_scroll":
            return (
                Action(ACTION_HORIZONTAL_SCROLL, amount=-1),
                Action(ACTION_HORIZONTAL_SCROLL, amount=1),
            )
        if mode_name == "volume":
            return Action(ACTION_VOLUME, amount=-1), Action(ACTION_VOLUME, amount=1)
        if mode_name == "zoom":
            return (
                Action(ACTION_KEY_COMBO, value=["ctrl", "minus"]),
                Action(ACTION_KEY_COMBO, value=["ctrl", "equal"]),
            )
        if mode_name == "tabs":
            return (
                Action(ACTION_KEY_COMBO, value=["ctrl", "shift", "tab"]),
                Action(ACTION_KEY_COMBO, value=["ctrl", "tab"]),
            )
        raise ValueError(f"unsupported rotation mode: {mode_name}")

    def build_profile(self) -> Profile:
        left, right = self._rotation_pair(self.mode)
        bindings = {
            GESTURE_ROTATE_LEFT: left,
            GESTURE_ROTATE_RIGHT: right,
        }

        for gesture, action_name in self.gesture_bindings.items():
            bindings[gesture] = (
                Action(ACTION_NOOP)
                if action_name == "noop"
                else Action(ACTION_KEY, value=action_name)
            )

        for modifier, mode_name in self.modifier_modes.items():
            if mode_name == "inherit":
                continue
            mod_left, mod_right = self._rotation_pair(mode_name)
            bindings[binding_key(GESTURE_ROTATE_LEFT, [modifier])] = mod_left
            bindings[binding_key(GESTURE_ROTATE_RIGHT, [modifier])] = mod_right

        return Profile(id="global", name="Global Default", bindings=bindings)

    def refresh_profile(self) -> None:
        with self.lock:
            if self.action_engine is not None:
                self.action_engine.set_profiles([self.build_profile()])

    def attach_action_engine(self, engine: ActionEngine) -> None:
        with self.lock:
            self.action_engine = engine
            self.action_engine.set_profiles([self.build_profile()])

    def detach_action_engine(self) -> None:
        with self.lock:
            self.action_engine = None

    def set_mode(self, mode: str) -> None:
        if mode not in {"scroll", "volume"}:
            raise ValueError("invalid mode")
        with self.lock:
            self.mode = mode
            self.save()
            self.refresh_profile()
        self.publish({"type": "mode", "mode": mode})

    def set_gesture_action(self, gesture: str, action_name: str) -> None:
        if gesture not in BUTTON_GESTURES:
            raise ValueError("invalid gesture")
        if action_name not in GESTURE_ACTIONS:
            raise ValueError("invalid action")
        with self.lock:
            self.gesture_bindings[gesture] = action_name
            self.save()
            self.refresh_profile()
        self.publish(
            {
                "type": "gesture_binding",
                "gesture": gesture,
                "action": action_name,
            }
        )
        if gesture == GESTURE_CLICK:
            self.publish({"type": "click_key", "click_key": action_name})

    def set_modifier_mode(self, modifier: str, mode_name: str) -> None:
        modifier = str(modifier).lower()
        if modifier not in MODIFIER_LAYERS:
            raise ValueError("invalid modifier")
        if mode_name not in MODIFIER_MODES:
            raise ValueError("invalid modifier mode")
        with self.lock:
            self.modifier_modes[modifier] = mode_name
            self.save()
            self.refresh_profile()
        self.publish(
            {
                "type": "modifier_binding",
                "modifier": modifier,
                "mode": mode_name,
                "modifier_modes": dict(self.modifier_modes),
            }
        )

    def set_click_key(self, click_key: str) -> None:
        if click_key not in CLICK_KEYS:
            raise ValueError("invalid click_key")
        self.set_gesture_action(GESTURE_CLICK, click_key)

    def set_modifier_runtime_state(
        self,
        *,
        devices: Optional[list[str]] = None,
        active: Optional[tuple[str, ...]] = None,
    ) -> None:
        changed = False
        with self.lock:
            if devices is not None and devices != self.modifier_devices:
                self.modifier_devices = list(devices)
                changed = True
            if active is not None and active != self.active_modifiers:
                self.active_modifiers = tuple(active)
                changed = True
        if changed:
            self.publish(
                {
                    "type": "modifiers",
                    "active": list(self.active_modifiers),
                    "devices": list(self.modifier_devices),
                    "available": bool(self.modifier_devices),
                }
            )

    def publish(self, item) -> None:
        dead = []
        with self.lock:
            clients = list(self.clients)
        for client in clients:
            try:
                client.put_nowait(item)
            except Exception:
                dead.append(client)
        if dead:
            with self.lock:
                for client in dead:
                    if client in self.clients:
                        self.clients.remove(client)

    def status(self) -> dict:
        with self.lock:
            modifiers_available = bool(self.modifier_devices)
            return {
                "schema_version": 3,
                "version": "0.3.0",
                "mode": self.mode,
                "device": self.device,
                "device_name": self.device_name,
                "connected": self.connected,
                "last_error": self.last_error,
                "click_key": self.click_key,
                "click_keys": list(CLICK_KEYS.keys()),
                "gesture_bindings": dict(self.gesture_bindings),
                "gesture_actions": sorted(GESTURE_ACTIONS),
                "modifier_modes": dict(self.modifier_modes),
                "modifier_mode_options": sorted(MODIFIER_MODES),
                "modifier_devices": list(self.modifier_devices),
                "active_modifiers": list(self.active_modifiers),
                "capabilities": {
                    "rotate": True,
                    "click": True,
                    "double_click": True,
                    "long_press": True,
                    "modifiers": modifiers_available,
                    "horizontal_scroll": True,
                    "zoom_layer": modifiers_available,
                    "tab_layer": modifiers_available,
                    "profiles": False,
                    "generic_hid": False,
                },
                "timing": {
                    "double_click_seconds": DOUBLE_CLICK_SECONDS,
                    "long_press_seconds": LONG_PRESS_SECONDS,
                },
            }


state = State()


def resolve_source() -> str:
    data = Path("/proc/bus/input/devices").read_text(encoding="utf-8")
    for block in data.strip().split("\n\n"):
        if f'Name="{DEVICE_NAME}"' not in block:
            continue
        if "REL=1040" not in block:
            continue
        for line in block.splitlines():
            if line.startswith("H: Handlers="):
                for token in line.split():
                    if token.startswith("event"):
                        return "/dev/input/" + token
    raise RuntimeError("MEETION knob event device not found")


def write_event(fd: int, ev_type: int, code: int, value: int) -> None:
    now = time.time()
    sec = int(now)
    usec = int((now - sec) * 1_000_000)
    os.write(fd, struct.pack(EVENT, sec, usec, ev_type, code, value))


def emit_key(fd: int, key: int) -> None:
    write_event(fd, EV_KEY, key, 1)
    write_event(fd, EV_SYN, SYN_REPORT, 0)
    write_event(fd, EV_KEY, key, 0)
    write_event(fd, EV_SYN, SYN_REPORT, 0)


def emit_combo(fd: int, keys: list[int]) -> None:
    if not keys:
        return
    for key in keys:
        write_event(fd, EV_KEY, key, 1)
    write_event(fd, EV_SYN, SYN_REPORT, 0)
    for key in reversed(keys):
        write_event(fd, EV_KEY, key, 0)
    write_event(fd, EV_SYN, SYN_REPORT, 0)


def emit_scroll(fd: int, amount: int) -> None:
    if amount == 0:
        return
    write_event(fd, EV_REL, REL_WHEEL, amount)
    write_event(fd, EV_SYN, SYN_REPORT, 0)


def emit_horizontal_scroll(fd: int, amount: int) -> None:
    if amount == 0:
        return
    write_event(fd, EV_REL, REL_HWHEEL, amount)
    write_event(fd, EV_SYN, SYN_REPORT, 0)


def create_uinput():
    mouse = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
    fcntl.ioctl(mouse, UI_SET_EVBIT, EV_REL)
    fcntl.ioctl(mouse, UI_SET_RELBIT, REL_WHEEL)
    fcntl.ioctl(mouse, UI_SET_RELBIT, REL_HWHEEL)
    mouse_dev = struct.pack(
        "80sHHHHi" + "i" * 64 * 4,
        b"KNOBController pointer",
        BUS_USB,
        0x320F,
        0x5055,
        3,
        0,
        *([0] * 64 * 4),
    )
    os.write(mouse, mouse_dev)
    fcntl.ioctl(mouse, UI_DEV_CREATE)

    keyboard = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
    fcntl.ioctl(keyboard, UI_SET_EVBIT, EV_KEY)
    fcntl.ioctl(keyboard, UI_SET_KEYBIT, KEY_VOLUMEUP)
    fcntl.ioctl(keyboard, UI_SET_KEYBIT, KEY_VOLUMEDOWN)
    for code in set(LINUX_KEYS.values()):
        fcntl.ioctl(keyboard, UI_SET_KEYBIT, code)
    keyboard_dev = struct.pack(
        "80sHHHHi" + "i" * 64 * 4,
        b"KNOBController actions",
        BUS_USB,
        0x320F,
        0x5055,
        3,
        0,
        *([0] * 64 * 4),
    )
    os.write(keyboard, keyboard_dev)
    fcntl.ioctl(keyboard, UI_DEV_CREATE)
    return mouse, keyboard


def publish_gesture(gesture: Gesture, action: Action) -> None:
    payload = {
        "type": "gesture",
        "gesture": gesture.name,
        "delta": gesture.delta,
        "modifiers": list(gesture.modifiers),
        "binding_key": gesture.binding_key,
        "action": {
            "type": action.type,
            "value": action.value,
            "amount": action.amount,
        },
    }
    if gesture.metadata:
        payload["metadata"] = dict(gesture.metadata)
    state.publish(payload)

    if gesture.name in {GESTURE_ROTATE_LEFT, GESTURE_ROTATE_RIGHT}:
        state.publish(
            {
                "type": "turn",
                "delta": gesture.delta,
                "mode": state.mode,
                "modifiers": list(gesture.modifiers),
                "action": action.type,
            }
        )
    elif gesture.name in BUTTON_GESTURES:
        state.publish(
            {
                "type": gesture.name,
                "action": action.value if action.type == ACTION_KEY else "noop",
                "modifiers": list(gesture.modifiers),
            }
        )
        if gesture.name == GESTURE_CLICK:
            state.publish({"type": "click", "click_key": state.click_key})


def process_modifier_fd(fd: int, modifier_state: ModifierState) -> None:
    try:
        data = os.read(fd, EVENT_SIZE * 64)
    except BlockingIOError:
        return
    usable = len(data) // EVENT_SIZE * EVENT_SIZE
    for idx in range(0, usable, EVENT_SIZE):
        _sec, _usec, ev_type, code, value = struct.unpack(
            EVENT,
            data[idx : idx + EVENT_SIZE],
        )
        if ev_type == EV_KEY:
            modifier_state.update(code, value)


def knob_loop() -> None:
    source = None
    mouse = None
    keyboard = None
    gesture_engine: Optional[GestureEngine] = None
    modifier_devices: Optional[ModifierDeviceSet] = None
    modifier_state = ModifierState()

    while state.running:
        try:
            source_path = resolve_source()
            state.device = source_path
            state.last_error = None
            source = os.open(source_path, os.O_RDONLY | os.O_NONBLOCK)
            mouse, keyboard = create_uinput()
            fcntl.ioctl(source, EVIOCGRAB, 1)

            modifier_paths = discover_modifier_devices(
                device_name=DEVICE_NAME,
                exclude_path=source_path,
            )
            modifier_devices = ModifierDeviceSet(modifier_paths)
            modifier_devices.open()
            state.set_modifier_runtime_state(
                devices=list(modifier_devices.opened_paths),
                active=(),
            )

            linux_executor = LinuxActionExecutor(
                keyboard_fd=keyboard,
                mouse_fd=mouse,
                keymap=LinuxKeyMap(
                    keys=LINUX_KEYS,
                    volume_up=KEY_VOLUMEUP,
                    volume_down=KEY_VOLUMEDOWN,
                ),
                emit_key=emit_key,
                emit_scroll=emit_scroll,
                emit_horizontal_scroll=emit_horizontal_scroll,
                emit_combo=emit_combo,
            )
            action_engine = ActionEngine(linux_executor)
            state.attach_action_engine(action_engine)

            def on_gesture(gesture: Gesture) -> None:
                action = action_engine.handle(gesture)
                publish_gesture(gesture, action)

            gesture_engine = GestureEngine(
                on_gesture,
                double_click_seconds=DOUBLE_CLICK_SECONDS,
                long_press_seconds=LONG_PRESS_SECONDS,
            )

            state.connected = True
            state.publish(
                {
                    "type": "device",
                    "connected": True,
                    "device": source_path,
                    "device_name": state.device_name,
                    "modifier_devices": list(modifier_devices.opened_paths),
                }
            )
            print(
                f"KNOBController v0.3 active: {source_path}; "
                f"modifier nodes={len(modifier_devices.fds)}",
                flush=True,
            )

            while state.running:
                watched = [source, *modifier_devices.fds]
                ready, _, _ = select.select(watched, [], [], 0.5)
                if not ready:
                    continue

                for ready_fd in ready:
                    if ready_fd != source:
                        process_modifier_fd(ready_fd, modifier_state)
                        active = modifier_state.current()
                        state.set_modifier_runtime_state(active=active)
                        continue

                    data = os.read(source, EVENT_SIZE * 64)
                    usable = len(data) // EVENT_SIZE * EVENT_SIZE
                    for idx in range(0, usable, EVENT_SIZE):
                        _sec, _usec, ev_type, code, value = struct.unpack(
                            EVENT,
                            data[idx : idx + EVENT_SIZE],
                        )
                        if ev_type != EV_KEY:
                            continue

                        modifiers = modifier_state.current()
                        if code == KEY_KNOB_CLICK:
                            if value == 1:
                                gesture_engine.button_press(modifiers)
                            elif value == 0:
                                gesture_engine.button_release(modifiers)
                            continue

                        if value != 1:
                            continue
                        if code == KEY_VOLUMEUP:
                            gesture_engine.rotate(1, modifiers)
                        elif code == KEY_VOLUMEDOWN:
                            gesture_engine.rotate(-1, modifiers)

        except Exception as exc:
            state.connected = False
            state.last_error = str(exc)
            state.publish(
                {
                    "type": "device",
                    "connected": False,
                    "error": str(exc),
                }
            )
            print(f"KNOBController loop error: {exc}", flush=True)
            time.sleep(2)
        finally:
            state.connected = False
            state.detach_action_engine()
            modifier_state.clear()
            state.set_modifier_runtime_state(devices=[], active=())

            if gesture_engine is not None:
                gesture_engine.close()
                gesture_engine = None
            if modifier_devices is not None:
                modifier_devices.close()
                modifier_devices = None

            for fd, destroy in [(source, False), (mouse, True), (keyboard, True)]:
                if fd is None:
                    continue
                try:
                    if destroy:
                        fcntl.ioctl(fd, UI_DEV_DESTROY)
                    else:
                        fcntl.ioctl(fd, EVIOCGRAB, 0)
                except Exception:
                    pass
                try:
                    os.close(fd)
                except Exception:
                    pass
            source = mouse = keyboard = None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, _format, *_args) -> None:
        return

    def send_json(self, data, status: int = 200) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("access-control-allow-origin", "*")
        self.send_header("access-control-allow-methods", "GET, POST, OPTIONS")
        self.send_header("access-control-allow-headers", "content-type")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("access-control-allow-origin", "*")
        self.send_header("access-control-allow-methods", "GET, POST, OPTIONS")
        self.send_header("access-control-allow-headers", "content-type")
        self.end_headers()

    def do_GET(self) -> None:
        if self.path == "/api/status":
            self.send_json(state.status())
            return

        if self.path == "/api/profiles":
            self.send_json(
                {
                    "active_profile": "global",
                    "profiles": [
                        {
                            "id": "global",
                            "name": "Global Default",
                            "application": None,
                            "enabled": True,
                            "live": True,
                        }
                    ],
                    "application_profiles_supported": False,
                }
            )
            return

        if self.path == "/events":
            client = queue.Queue(maxsize=256)
            with state.lock:
                state.clients.append(client)
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("cache-control", "no-cache")
            self.send_header("connection", "keep-alive")
            self.send_header("access-control-allow-origin", "*")
            self.end_headers()
            try:
                initial = {"type": "status", **state.status()}
                self.wfile.write(
                    f"data: {json.dumps(initial)}\n\n".encode("utf-8")
                )
                self.wfile.flush()
                while state.running:
                    try:
                        item = client.get(timeout=15)
                    except queue.Empty:
                        self.wfile.write(b": heartbeat\n\n")
                        self.wfile.flush()
                        continue
                    self.wfile.write(
                        f"data: {json.dumps(item)}\n\n".encode("utf-8")
                    )
                    self.wfile.flush()
            except Exception:
                pass
            finally:
                with state.lock:
                    if client in state.clients:
                        state.clients.remove(client)
            return

        self.send_json({"error": "not found"}, 404)

    def do_POST(self) -> None:
        try:
            length = int(self.headers.get("content-length", "0"))
            data = json.loads(self.rfile.read(length) or b"{}")
        except Exception as exc:
            self.send_json({"error": f"invalid json: {exc}"}, 400)
            return

        if self.path == "/api/mode":
            try:
                state.set_mode(data.get("mode"))
                self.send_json({"mode": state.mode})
            except Exception as exc:
                self.send_json({"error": str(exc)}, 400)
            return

        if self.path == "/api/click-map":
            try:
                state.set_click_key(data.get("click_key"))
                self.send_json({"click_key": state.click_key})
            except Exception as exc:
                self.send_json({"error": str(exc)}, 400)
            return

        if self.path == "/api/gesture-map":
            try:
                gesture = data.get("gesture")
                action_name = data.get("action")
                state.set_gesture_action(gesture, action_name)
                self.send_json(
                    {
                        "gesture": gesture,
                        "action": state.gesture_bindings[gesture],
                        "gesture_bindings": dict(state.gesture_bindings),
                    }
                )
            except Exception as exc:
                self.send_json({"error": str(exc)}, 400)
            return

        if self.path == "/api/modifier-map":
            try:
                modifier = data.get("modifier")
                mode_name = data.get("mode")
                state.set_modifier_mode(modifier, mode_name)
                self.send_json(
                    {
                        "modifier": modifier,
                        "mode": state.modifier_modes[modifier],
                        "modifier_modes": dict(state.modifier_modes),
                    }
                )
            except Exception as exc:
                self.send_json({"error": str(exc)}, 400)
            return

        self.send_json({"error": "not found"}, 404)


def stop(_signum, _frame) -> None:
    state.running = False


def main() -> None:
    state.load()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    threading.Thread(target=knob_loop, daemon=True).start()

    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.timeout = 1.0
    print(f"KNOBController v0.3 daemon API: http://{HOST}:{PORT}", flush=True)
    while state.running:
        server.handle_request()
    server.server_close()


if __name__ == "__main__":
    main()
