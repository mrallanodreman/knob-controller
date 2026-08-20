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
from http.server import ThreadingHTTPServer

import knob_controller_daemon as core

from . import __version__
from .backends import ModifierDeviceSet, ModifierState, discover_modifier_devices
from .calibration import CalibrationManager
from .devices import DeviceService

HOST = core.HOST
PORT = core.PORT


device_service = DeviceService()


def _candidate(candidate_id: str):
    return device_service.candidate(candidate_id)


calibration = CalibrationManager(
    event_struct=core.EVENT,
    event_size=core.EVENT_SIZE,
    candidate_resolver=_candidate,
    publish=core.state.publish,
)


def resolve_source() -> str:
    preferred = device_service.resolve_preferred()
    core.state.device_name = preferred.name
    core.DEVICE_NAME = preferred.metadata.get("input_name", preferred.name)
    return preferred.event_path


def status() -> dict:
    data = core.state.status()
    data["version"] = __version__
    data["device_discovery"] = device_service.status(selected_path=core.state.device)
    data["calibration"] = calibration.status()
    data["runtime_decoder"] = (
        "EV_REL+EV_KEY" if device_service.runtime_map.left.ev_type == core.EV_REL else "EV_KEY"
    )
    capabilities = data.setdefault("capabilities", {})
    capabilities["device_discovery"] = True
    capabilities["generic_hid"] = any(
        item.adapter_id == "generic-hid" for item in device_service.discover()
    )
    capabilities["interactive_calibration"] = True
    capabilities["calibration_ui"] = True
    capabilities["ev_rel_rotary"] = True
    return data


def knob_loop() -> None:
    source = mouse = keyboard = None
    gesture_engine = None
    modifier_devices = None
    modifier_state = ModifierState()

    while core.state.running:
        try:
            source_path = resolve_source()
            event_map = device_service.runtime_map
            core.state.device = source_path
            core.state.last_error = None
            source = os.open(source_path, os.O_RDONLY | os.O_NONBLOCK)
            mouse, keyboard = core.create_uinput()
            fcntl.ioctl(source, core.EVIOCGRAB, 1)

            modifier_paths = discover_modifier_devices(
                device_name=core.DEVICE_NAME,
                exclude_path=source_path,
            )
            modifier_devices = ModifierDeviceSet(modifier_paths)
            modifier_devices.open()
            core.state.set_modifier_runtime_state(
                devices=list(modifier_devices.opened_paths), active=()
            )

            executor = core.LinuxActionExecutor(
                keyboard_fd=keyboard,
                mouse_fd=mouse,
                keymap=core.LinuxKeyMap(
                    keys=core.LINUX_KEYS,
                    volume_up=core.KEY_VOLUMEUP,
                    volume_down=core.KEY_VOLUMEDOWN,
                ),
                emit_key=core.emit_key,
                emit_scroll=core.emit_scroll,
                emit_horizontal_scroll=core.emit_horizontal_scroll,
                emit_combo=core.emit_combo,
            )
            action_engine = core.ActionEngine(executor)
            core.state.attach_action_engine(action_engine)

            def on_gesture(gesture) -> None:
                action = action_engine.handle(gesture)
                core.publish_gesture(gesture, action)

            gesture_engine = core.GestureEngine(
                on_gesture,
                double_click_seconds=core.DOUBLE_CLICK_SECONDS,
                long_press_seconds=core.LONG_PRESS_SECONDS,
            )

            core.state.connected = True
            core.state.publish(
                {
                    "type": "device",
                    "connected": True,
                    "device": source_path,
                    "device_name": core.state.device_name,
                    "adapter": getattr(device_service.active_candidate, "adapter_id", None),
                    "decoder": (
                        "EV_REL+EV_KEY"
                        if event_map.left.ev_type == core.EV_REL
                        else "EV_KEY"
                    ),
                    "modifier_devices": list(modifier_devices.opened_paths),
                }
            )
            print(
                f"KNOBController v{__version__} active: {source_path} "
                f"adapter={getattr(device_service.active_candidate, 'adapter_id', 'unknown')}",
                flush=True,
            )

            while core.state.running:
                watched = [source, *modifier_devices.fds]
                ready, _, _ = select.select(watched, [], [], 0.5)
                if not ready:
                    continue
                for ready_fd in ready:
                    if ready_fd != source:
                        core.process_modifier_fd(ready_fd, modifier_state)
                        core.state.set_modifier_runtime_state(active=modifier_state.current())
                        continue

                    data = os.read(source, core.EVENT_SIZE * 64)
                    usable = len(data) // core.EVENT_SIZE * core.EVENT_SIZE
                    for idx in range(0, usable, core.EVENT_SIZE):
                        _sec, _usec, ev_type, code, value = struct.unpack(
                            core.EVENT, data[idx : idx + core.EVENT_SIZE]
                        )
                        decoded = event_map.classify(ev_type, code, value)
                        if decoded is None:
                            continue
                        kind, decoded_value = decoded
                        modifiers = modifier_state.current()
                        if kind == "press":
                            if decoded_value == 1:
                                gesture_engine.button_press(modifiers)
                            elif decoded_value == 0:
                                gesture_engine.button_release(modifiers)
                        elif kind == "left":
                            gesture_engine.rotate(-1, modifiers)
                        elif kind == "right":
                            gesture_engine.rotate(1, modifiers)

        except Exception as exc:
            core.state.connected = False
            core.state.last_error = str(exc)
            core.state.publish(
                {"type": "device", "connected": False, "error": str(exc)}
            )
            print(f"KNOBController v{__version__} loop error: {exc}", flush=True)
            time.sleep(2)
        finally:
            core.state.connected = False
            core.state.detach_action_engine()
            modifier_state.clear()
            core.state.set_modifier_runtime_state(devices=[], active=())
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
                        fcntl.ioctl(fd, core.UI_DEV_DESTROY)
                    else:
                        fcntl.ioctl(fd, core.EVIOCGRAB, 0)
                except Exception:
                    pass
                try:
                    os.close(fd)
                except Exception:
                    pass
            source = mouse = keyboard = None


class Handler(core.Handler):
    def do_GET(self) -> None:
        if self.path == "/api/status":
            self.send_json(status())
            return
        if self.path == "/api/devices":
            devices = device_service.discover()
            self.send_json(
                {
                    "version": __version__,
                    "devices": [item.to_json() for item in devices],
                    "selected": core.state.device,
                    "selection_policy": "known-or-calibrated-first",
                }
            )
            return
        if self.path == "/api/calibration":
            self.send_json(calibration.status())
            return
        if self.path == "/events":
            self._events()
            return
        super().do_GET()

    def _events(self) -> None:
        client = queue.Queue(maxsize=256)
        with core.state.lock:
            core.state.clients.append(client)
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("cache-control", "no-cache")
        self.send_header("connection", "keep-alive")
        self.send_header("access-control-allow-origin", "*")
        self.end_headers()
        try:
            self.wfile.write(f"data: {json.dumps({'type': 'status', **status()})}\n\n".encode())
            self.wfile.flush()
            while core.state.running:
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
            with core.state.lock:
                if client in core.state.clients:
                    core.state.clients.remove(client)

    def do_POST(self) -> None:
        if self.path not in {
            "/api/calibration/start",
            "/api/calibration/arm",
            "/api/calibration/cancel",
            "/api/calibration/save",
        }:
            super().do_POST()
            return
        try:
            length = int(self.headers.get("content-length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            if self.path == "/api/calibration/start":
                result = calibration.start(
                    str(payload.get("device_id") or ""),
                    active_path=core.state.device,
                    connected=core.state.connected,
                )
            elif self.path == "/api/calibration/arm":
                result = calibration.arm(str(payload.get("step") or ""))
            elif self.path == "/api/calibration/cancel":
                result = calibration.cancel()
            else:
                result = calibration.save(payload.get("name"))
            self.send_json(result)
        except Exception as exc:
            self.send_json({"error": str(exc)}, 400)


def stop(_signum, _frame) -> None:
    core.state.running = False


def main() -> None:
    core.state.load()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    threading.Thread(target=knob_loop, daemon=True).start()

    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.timeout = 1.0
    print(f"KNOBController v{__version__} API: http://{HOST}:{PORT}", flush=True)
    while core.state.running:
        server.handle_request()
    server.server_close()


if __name__ == "__main__":
    main()
