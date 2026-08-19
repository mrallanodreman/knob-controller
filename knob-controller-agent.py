#!/usr/bin/env python3
"""KNOBController v0.4 per-application profile agent.

Runs unprivileged inside the user's desktop session. It detects the foreground
application, chooses a profile, and applies that profile to the local hardware
daemon at 127.0.0.1:8766.

The privileged daemon never needs DISPLAY/X11 access. This keeps desktop
context detection separated from evdev/uinput hardware handling.
"""

from __future__ import annotations

import json
import os
import queue
import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, Iterable, Optional
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen

from app_context import AppContext, AppProfile, X11ForegroundDetector, choose_profile

DAEMON_API = "http://127.0.0.1:8766"
AGENT_HOST = "127.0.0.1"
AGENT_PORT = 8767
POLL_SECONDS = 0.45
CONFIG_PATH = Path.home() / ".config" / "knob-controller" / "profiles.json"

DEFAULT_PROFILES = [
    AppProfile(
        id="global",
        name="Global",
        match=(),
        mode="scroll",
        gesture_bindings={
            "click": "mute",
            "double_click": "noop",
            "long_press": "noop",
        },
        modifier_modes={
            "ctrl": "zoom",
            "shift": "horizontal_scroll",
            "alt": "tabs",
        },
    ),
    AppProfile(
        id="browser",
        name="Browser",
        match=("firefox", "chromium", "google-chrome", "brave", "vivaldi", "microsoft-edge"),
        mode="scroll",
        gesture_bindings={"click": "enter", "double_click": "noop", "long_press": "esc"},
        modifier_modes={"ctrl": "zoom", "shift": "horizontal_scroll", "alt": "tabs"},
    ),
    AppProfile(
        id="media",
        name="Media",
        match=("spotify", "vlc", "rhythmbox", "audacious", "mpv"),
        mode="volume",
        gesture_bindings={"click": "playpause", "double_click": "mute", "long_press": "noop"},
        modifier_modes={"ctrl": "inherit", "shift": "inherit", "alt": "inherit"},
    ),
    AppProfile(
        id="video",
        name="Video Editor",
        match=("kdenlive", "resolve", "davinci", "premiere", "olive"),
        mode="scroll",
        gesture_bindings={"click": "space", "double_click": "noop", "long_press": "esc"},
        modifier_modes={"ctrl": "zoom", "shift": "horizontal_scroll", "alt": "tabs"},
    ),
    AppProfile(
        id="design",
        name="Design",
        match=("gimp", "krita", "inkscape", "photoshop"),
        mode="scroll",
        gesture_bindings={"click": "enter", "double_click": "noop", "long_press": "esc"},
        modifier_modes={"ctrl": "zoom", "shift": "horizontal_scroll", "alt": "inherit"},
    ),
    AppProfile(
        id="ide",
        name="IDE",
        match=("code", "codium", "jetbrains", "pycharm", "idea", "sublime_text"),
        mode="scroll",
        gesture_bindings={"click": "enter", "double_click": "noop", "long_press": "esc"},
        modifier_modes={"ctrl": "zoom", "shift": "horizontal_scroll", "alt": "tabs"},
    ),
]


class AgentState:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.running = True
        self.clients: list[queue.Queue] = []
        self.profiles = list(DEFAULT_PROFILES)
        self.active_profile_id = "global"
        self.context = AppContext(backend="unknown", available=False, detail="starting")
        self.daemon_online = False
        self.last_error: Optional[str] = None
        self.last_applied: Dict[str, object] = {}

    def publish(self, payload: dict) -> None:
        dead = []
        with self.lock:
            clients = list(self.clients)
        for client in clients:
            try:
                client.put_nowait(payload)
            except Exception:
                dead.append(client)
        if dead:
            with self.lock:
                for client in dead:
                    if client in self.clients:
                        self.clients.remove(client)

    def status(self) -> dict:
        with self.lock:
            return {
                "version": "0.4.0",
                "active_profile": self.active_profile_id,
                "foreground_app": {
                    "backend": self.context.backend,
                    "app_id": self.context.app_id,
                    "title": self.context.title,
                    "available": self.context.available,
                    "detail": self.context.detail,
                },
                "daemon_online": self.daemon_online,
                "last_error": self.last_error,
                "profiles": [profile_to_json(profile) for profile in self.profiles],
            }


state = AgentState()


def profile_to_json(profile: AppProfile) -> dict:
    return {
        "id": profile.id,
        "name": profile.name,
        "match": list(profile.match),
        "mode": profile.mode,
        "gesture_bindings": dict(profile.gesture_bindings),
        "modifier_modes": dict(profile.modifier_modes),
        "enabled": profile.enabled,
    }


def profile_from_json(data: dict) -> AppProfile:
    profile_id = str(data.get("id", "")).strip()
    if not profile_id:
        raise ValueError("profile id is required")
    return AppProfile(
        id=profile_id,
        name=str(data.get("name") or profile_id),
        match=tuple(str(item).lower() for item in data.get("match", []) if str(item).strip()),
        mode=data.get("mode"),
        gesture_bindings=dict(data.get("gesture_bindings") or {}),
        modifier_modes=dict(data.get("modifier_modes") or {}),
        enabled=bool(data.get("enabled", True)),
    )


def ensure_config() -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if CONFIG_PATH.exists():
        return
    CONFIG_PATH.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "profiles": [profile_to_json(profile) for profile in DEFAULT_PROFILES],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def load_profiles() -> list[AppProfile]:
    ensure_config()
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        profiles = [profile_from_json(item) for item in data.get("profiles", [])]
        if not any(profile.id == "global" for profile in profiles):
            profiles.insert(0, DEFAULT_PROFILES[0])
        return profiles or list(DEFAULT_PROFILES)
    except Exception as exc:
        state.last_error = f"profile config load failed: {exc}"
        return list(DEFAULT_PROFILES)


def api_post(path: str, payload: dict) -> dict:
    request = Request(
        DAEMON_API + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=1.25) as response:
        return json.loads(response.read() or b"{}")


def apply_profile(profile: AppProfile) -> None:
    desired = {
        "mode": profile.mode,
        "gesture_bindings": dict(profile.gesture_bindings),
        "modifier_modes": dict(profile.modifier_modes),
    }
    if desired == state.last_applied and state.daemon_online:
        return

    if profile.mode:
        api_post("/api/mode", {"mode": profile.mode})
    for gesture, action in profile.gesture_bindings.items():
        api_post("/api/gesture-map", {"gesture": gesture, "action": action})
    for modifier, mode in profile.modifier_modes.items():
        api_post("/api/modifier-map", {"modifier": modifier, "mode": mode})

    state.daemon_online = True
    state.last_error = None
    state.last_applied = desired


def monitoring_loop() -> None:
    detector = X11ForegroundDetector()
    last_profile = None
    last_context_key = None

    while state.running:
        context = detector.detect()
        with state.lock:
            state.context = context
            profiles = list(state.profiles)

        profile_id = choose_profile(profiles, context, default_id="global")
        profile = next((item for item in profiles if item.id == profile_id), profiles[0])

        context_key = (context.backend, context.app_id, context.title, context.available)
        changed = profile_id != last_profile or context_key != last_context_key

        try:
            apply_profile(profile)
        except (URLError, HTTPError, OSError, ValueError) as exc:
            state.daemon_online = False
            state.last_error = str(exc)
            state.last_applied = {}

        with state.lock:
            state.active_profile_id = profile_id

        if changed:
            state.publish(
                {
                    "type": "profile",
                    "active_profile": profile_id,
                    "profile": profile_to_json(profile),
                    "foreground_app": {
                        "backend": context.backend,
                        "app_id": context.app_id,
                        "title": context.title,
                        "available": context.available,
                        "detail": context.detail,
                    },
                    "daemon_online": state.daemon_online,
                }
            )
            last_profile = profile_id
            last_context_key = context_key

        time.sleep(POLL_SECONDS)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, _format, *_args) -> None:
        return

    def send_json(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("access-control-allow-origin", "*")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/api/status":
            self.send_json(state.status())
            return
        if self.path == "/api/profiles":
            snapshot = state.status()
            self.send_json(
                {
                    "active_profile": snapshot["active_profile"],
                    "foreground_app": snapshot["foreground_app"],
                    "profiles": snapshot["profiles"],
                    "application_profiles_supported": snapshot["foreground_app"]["backend"] == "x11",
                }
            )
            return
        if self.path == "/events":
            client = queue.Queue(maxsize=128)
            with state.lock:
                state.clients.append(client)
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("cache-control", "no-cache")
            self.send_header("access-control-allow-origin", "*")
            self.end_headers()
            try:
                self.wfile.write(f"data: {json.dumps({'type': 'status', **state.status()})}\n\n".encode())
                self.wfile.flush()
                while state.running:
                    try:
                        item = client.get(timeout=15)
                    except queue.Empty:
                        self.wfile.write(b": heartbeat\n\n")
                        self.wfile.flush()
                        continue
                    self.wfile.write(f"data: {json.dumps(item)}\n\n".encode())
                    self.wfile.flush()
            except Exception:
                pass
            finally:
                with state.lock:
                    if client in state.clients:
                        state.clients.remove(client)
            return
        self.send_json({"error": "not found"}, 404)


def stop(_signum, _frame) -> None:
    state.running = False


def main() -> None:
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    state.profiles = load_profiles()
    threading.Thread(target=monitoring_loop, daemon=True).start()

    server = ThreadingHTTPServer((AGENT_HOST, AGENT_PORT), Handler)
    server.timeout = 1.0
    print(f"KNOBController v0.4 profile agent: http://{AGENT_HOST}:{AGENT_PORT}", flush=True)
    while state.running:
        server.handle_request()
    server.server_close()


if __name__ == "__main__":
    main()
