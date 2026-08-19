#!/usr/bin/env python3
"""KNOBController v0.5 per-application profile agent.

Runs unprivileged inside the desktop session. It detects the foreground app,
selects a profile and applies it to the privileged hardware daemon. v0.5 adds
an editable localhost API so the Tauri UI can manage profiles without touching
JSON by hand.
"""
from __future__ import annotations

import json
import queue
import re
import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app_context import AppContext, AppProfile, X11ForegroundDetector, choose_profile

DAEMON_API = "http://127.0.0.1:8766"
AGENT_HOST = "127.0.0.1"
AGENT_PORT = 8767
POLL_SECONDS = 0.45
CONFIG_PATH = Path.home() / ".config" / "knob-controller" / "profiles.json"

GESTURE_ACTIONS = {"noop", "mute", "enter", "esc", "tab", "space", "playpause"}
MODIFIER_MODES = {"inherit", "scroll", "horizontal_scroll", "volume", "zoom", "tabs"}
BASE_MODES = {"scroll", "volume"}


def default_profiles() -> list[AppProfile]:
    return [
        AppProfile("global", "Global", (), "scroll",
                   {"click":"mute","double_click":"noop","long_press":"noop"},
                   {"ctrl":"zoom","shift":"horizontal_scroll","alt":"tabs"}),
        AppProfile("browser", "Browser", ("firefox","chromium","google-chrome","brave","vivaldi","microsoft-edge"), "scroll",
                   {"click":"enter","double_click":"noop","long_press":"esc"},
                   {"ctrl":"zoom","shift":"horizontal_scroll","alt":"tabs"}),
        AppProfile("media", "Media", ("spotify","vlc","rhythmbox","audacious","mpv"), "volume",
                   {"click":"playpause","double_click":"mute","long_press":"noop"},
                   {"ctrl":"inherit","shift":"inherit","alt":"inherit"}),
        AppProfile("video", "Video Editor", ("kdenlive","resolve","davinci","premiere","olive"), "scroll",
                   {"click":"space","double_click":"noop","long_press":"esc"},
                   {"ctrl":"zoom","shift":"horizontal_scroll","alt":"tabs"}),
        AppProfile("design", "Design", ("gimp","krita","inkscape","photoshop"), "scroll",
                   {"click":"enter","double_click":"noop","long_press":"esc"},
                   {"ctrl":"zoom","shift":"horizontal_scroll","alt":"inherit"}),
        AppProfile("ide", "IDE", ("code","codium","jetbrains","pycharm","idea","sublime_text"), "scroll",
                   {"click":"enter","double_click":"noop","long_press":"esc"},
                   {"ctrl":"zoom","shift":"horizontal_scroll","alt":"tabs"}),
    ]

DEFAULT_PROFILES = default_profiles()


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


def slugify(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return value or "profile"


def normalize_profile(data: dict, *, existing_id: Optional[str] = None) -> AppProfile:
    name = str(data.get("name") or "New Profile").strip()
    profile_id = str(data.get("id") or existing_id or slugify(name)).strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", profile_id):
        raise ValueError("invalid profile id")
    mode = str(data.get("mode") or "scroll")
    if mode not in BASE_MODES:
        raise ValueError("mode must be scroll or volume")

    matches = []
    for item in data.get("match", []):
        item = str(item).strip().lower()
        if item and item not in matches:
            matches.append(item)

    gestures = {"click":"noop","double_click":"noop","long_press":"noop"}
    for key, value in dict(data.get("gesture_bindings") or {}).items():
        if key in gestures and value in GESTURE_ACTIONS:
            gestures[key] = value

    modifiers = {"ctrl":"inherit","shift":"inherit","alt":"inherit"}
    for key, value in dict(data.get("modifier_modes") or {}).items():
        if key in modifiers and value in MODIFIER_MODES:
            modifiers[key] = value

    return AppProfile(
        id=profile_id,
        name=name or profile_id,
        match=tuple(matches),
        mode=mode,
        gesture_bindings=gestures,
        modifier_modes=modifiers,
        enabled=bool(data.get("enabled", True)),
    )


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
        self.revision = 0

    def publish(self, payload: dict) -> None:
        dead = []
        with self.lock:
            clients = list(self.clients)
        for client in clients:
            try: client.put_nowait(payload)
            except Exception: dead.append(client)
        if dead:
            with self.lock:
                for client in dead:
                    if client in self.clients: self.clients.remove(client)

    def status(self) -> dict:
        with self.lock:
            return {
                "version":"0.5.0",
                "revision":self.revision,
                "active_profile":self.active_profile_id,
                "foreground_app":{
                    "backend":self.context.backend,
                    "app_id":self.context.app_id,
                    "title":self.context.title,
                    "available":self.context.available,
                    "detail":self.context.detail,
                },
                "daemon_online":self.daemon_online,
                "last_error":self.last_error,
                "profiles":[profile_to_json(p) for p in self.profiles],
            }

state = AgentState()


def persist_profiles() -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version":2,"profiles":[profile_to_json(p) for p in state.profiles]}
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(CONFIG_PATH)


def ensure_config() -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        persist_profiles()


def load_profiles() -> list[AppProfile]:
    ensure_config()
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        profiles = [normalize_profile(item) for item in data.get("profiles", [])]
        if not any(p.id == "global" for p in profiles): profiles.insert(0, DEFAULT_PROFILES[0])
        return profiles or list(DEFAULT_PROFILES)
    except Exception as exc:
        state.last_error = f"profile config load failed: {exc}"
        return list(DEFAULT_PROFILES)


def mutate_profiles(mutator) -> None:
    with state.lock:
        mutator(state.profiles)
        if not any(p.id == "global" for p in state.profiles):
            state.profiles.insert(0, DEFAULT_PROFILES[0])
        state.revision += 1
        state.last_applied = {}
        persist_profiles()
        snapshot = state.status()
    state.publish({"type":"profiles_changed", **snapshot})


def api_post(path: str, payload: dict) -> dict:
    req = Request(DAEMON_API + path, data=json.dumps(payload).encode(), headers={"content-type":"application/json"}, method="POST")
    with urlopen(req, timeout=1.25) as response:
        return json.loads(response.read() or b"{}")


def apply_profile(profile: AppProfile) -> None:
    desired = {"mode":profile.mode,"gesture_bindings":dict(profile.gesture_bindings),"modifier_modes":dict(profile.modifier_modes)}
    if desired == state.last_applied and state.daemon_online: return
    if profile.mode: api_post("/api/mode", {"mode":profile.mode})
    for gesture, action in profile.gesture_bindings.items(): api_post("/api/gesture-map", {"gesture":gesture,"action":action})
    for modifier, mode in profile.modifier_modes.items(): api_post("/api/modifier-map", {"modifier":modifier,"mode":mode})
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
        profile = next((p for p in profiles if p.id == profile_id), profiles[0])
        context_key = (context.backend, context.app_id, context.title, context.available)
        changed = profile_id != last_profile or context_key != last_context_key
        try: apply_profile(profile)
        except (URLError, HTTPError, OSError, ValueError) as exc:
            state.daemon_online = False
            state.last_error = str(exc)
            state.last_applied = {}
        with state.lock: state.active_profile_id = profile_id
        if changed:
            state.publish({"type":"profile","active_profile":profile_id,"profile":profile_to_json(profile),"foreground_app":state.status()["foreground_app"],"daemon_online":state.daemon_online})
            last_profile, last_context_key = profile_id, context_key
        time.sleep(POLL_SECONDS)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, _format, *_args): return

    def _cors(self):
        self.send_header("access-control-allow-origin", "*")
        self.send_header("access-control-allow-methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("access-control-allow-headers", "content-type")

    def send_json(self, data: dict, status: int = 200):
        body = json.dumps(data).encode()
        self.send_response(status); self.send_header("content-type","application/json"); self._cors(); self.send_header("content-length",str(len(body))); self.end_headers(); self.wfile.write(body)

    def read_json(self) -> dict:
        length = int(self.headers.get("content-length","0"))
        return json.loads(self.rfile.read(length) or b"{}")

    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.end_headers()

    def do_GET(self):
        if self.path == "/api/status": self.send_json(state.status()); return
        if self.path == "/api/profiles":
            s = state.status(); self.send_json({"active_profile":s["active_profile"],"foreground_app":s["foreground_app"],"profiles":s["profiles"],"revision":s["revision"],"application_profiles_supported":s["foreground_app"]["backend"]=="x11"}); return
        if self.path == "/events":
            client = queue.Queue(maxsize=128)
            with state.lock: state.clients.append(client)
            self.send_response(200); self.send_header("content-type","text/event-stream"); self.send_header("cache-control","no-cache"); self._cors(); self.end_headers()
            try:
                self.wfile.write(f"data: {json.dumps({'type':'status',**state.status()})}\n\n".encode()); self.wfile.flush()
                while state.running:
                    try: item = client.get(timeout=15)
                    except queue.Empty: self.wfile.write(b": heartbeat\n\n"); self.wfile.flush(); continue
                    self.wfile.write(f"data: {json.dumps(item)}\n\n".encode()); self.wfile.flush()
            except Exception: pass
            finally:
                with state.lock:
                    if client in state.clients: state.clients.remove(client)
            return
        self.send_json({"error":"not found"},404)

    def do_POST(self):
        try: data = self.read_json()
        except Exception as exc: self.send_json({"error":f"invalid json: {exc}"},400); return
        try:
            if self.path == "/api/profiles":
                profile = normalize_profile(data)
                def add(items):
                    if any(p.id == profile.id for p in items): raise ValueError("profile id already exists")
                    items.append(profile)
                mutate_profiles(add); self.send_json({"profile":profile_to_json(profile)},201); return
            if self.path.startswith("/api/profiles/"):
                profile_id = self.path.rsplit("/",1)[-1]
                if profile_id == "global" and data.get("id") not in (None,"global"): raise ValueError("global profile id cannot change")
                replacement = normalize_profile({**data,"id":profile_id}, existing_id=profile_id)
                def replace(items):
                    for i,p in enumerate(items):
                        if p.id == profile_id: items[i]=replacement; return
                    raise ValueError("profile not found")
                mutate_profiles(replace); self.send_json({"profile":profile_to_json(replacement)}); return
            if self.path == "/api/profiles/reorder":
                order = [str(x) for x in data.get("order",[])]
                def reorder(items):
                    by_id = {p.id:p for p in items}; used=[]
                    for pid in order:
                        if pid in by_id and pid not in used: used.append(pid)
                    used += [p.id for p in items if p.id not in used]
                    items[:] = [by_id[pid] for pid in used]
                mutate_profiles(reorder); self.send_json({"profiles":state.status()["profiles"]}); return
            if self.path == "/api/profiles/use-current-app":
                profile_id = str(data.get("profile_id", ""))
                ctx = state.context
                token = (ctx.app_id or ctx.title).strip().lower()
                if not token: raise ValueError("no foreground application detected")
                def bind(items):
                    for i,p in enumerate(items):
                        if p.id == profile_id:
                            match=list(p.match)
                            if token not in match: match.append(token)
                            items[i]=AppProfile(p.id,p.name,tuple(match),p.mode,p.gesture_bindings,p.modifier_modes,p.enabled); return
                    raise ValueError("profile not found")
                mutate_profiles(bind); self.send_json({"profile_id":profile_id,"match":token}); return
        except ValueError as exc:
            self.send_json({"error":str(exc)},400); return
        self.send_json({"error":"not found"},404)

    def do_DELETE(self):
        if not self.path.startswith("/api/profiles/"): self.send_json({"error":"not found"},404); return
        profile_id = self.path.rsplit("/",1)[-1]
        if profile_id == "global": self.send_json({"error":"global profile cannot be deleted"},400); return
        try:
            def delete(items):
                before=len(items); items[:] = [p for p in items if p.id != profile_id]
                if len(items)==before: raise ValueError("profile not found")
            mutate_profiles(delete); self.send_json({"deleted":profile_id})
        except ValueError as exc: self.send_json({"error":str(exc)},404)


def stop(_signum,_frame): state.running=False

def main():
    signal.signal(signal.SIGTERM, stop); signal.signal(signal.SIGINT, stop)
    state.profiles = load_profiles()
    threading.Thread(target=monitoring_loop, daemon=True).start()
    server=ThreadingHTTPServer((AGENT_HOST,AGENT_PORT),Handler); server.timeout=1.0
    print(f"KNOBController v0.5 profile agent: http://{AGENT_HOST}:{AGENT_PORT}", flush=True)
    while state.running: server.handle_request()
    server.server_close()

if __name__ == "__main__": main()
