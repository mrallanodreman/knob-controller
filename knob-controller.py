#!/usr/bin/env python3
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

HOST = "127.0.0.1"
PORT = 8766
CONFIG_PATH = Path("/etc/knob-controller/config.json")

EV_SYN = 0
EV_KEY = 1
EV_REL = 2
SYN_REPORT = 0
KEY_VOLUMEDOWN = 114
KEY_VOLUMEUP = 115
REL_WHEEL = 8
BUS_USB = 0x03

# El botón del knob (empuje) manda KEY_MUTE (113) por el mismo evdev que el
# giro — confirmado en vivo (log "unhandled EV_KEY code=113"), no adivinado.
KEY_KNOB_CLICK = 113

# Opciones de remapeo para el clic: nombre visible <-> código evdev que se
# inyecta por /dev/uinput. "mute" reproduce el comportamiento nativo del
# hardware (silencio del sistema); el resto son remapeos reales.
CLICK_KEYS = {
    "mute": 113,       # KEY_MUTE — comportamiento nativo, valor por defecto
    "enter": 28,       # KEY_ENTER
    "esc": 1,          # KEY_ESC
    "tab": 15,         # KEY_TAB
    "space": 57,       # KEY_SPACE
    "playpause": 164,  # KEY_PLAYPAUSE
}
DEFAULT_CLICK_KEY = "mute"

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


HTML = r"""
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>KNOBController</title>
  <style>
    :root { color-scheme: dark; font-family: Inter, system-ui, sans-serif; }
    body { margin: 0; min-height: 100vh; display: grid; place-items: center; background: radial-gradient(circle at top, #25304f, #080a12 62%); color: #eef3ff; }
    main { width: min(920px, calc(100vw - 28px)); display: grid; grid-template-columns: 1fr 1fr; gap: 28px; align-items: center; }
    .card { background: rgba(12, 16, 29, .72); border: 1px solid rgba(145, 170, 255, .22); box-shadow: 0 24px 80px rgba(0,0,0,.42); border-radius: 30px; padding: 28px; backdrop-filter: blur(18px); }
    h1 { margin: 0 0 10px; font-size: clamp(34px, 5vw, 58px); letter-spacing: -0.06em; }
    p { color: #aab5d6; line-height: 1.55; }
    .knob-wrap { display: grid; place-items: center; min-height: 430px; }
    .knob { width: 290px; aspect-ratio: 1; border-radius: 50%; position: relative; background: linear-gradient(145deg, #1a2038, #050812); box-shadow: inset 18px 18px 42px rgba(0,0,0,.78), inset -12px -12px 35px rgba(106,126,190,.22), 0 30px 80px rgba(0,0,0,.62); transform: rotate(var(--angle, 0deg)); transition: transform .12s cubic-bezier(.2,.9,.1,1); }
    .knob::before { content: ""; position: absolute; inset: 22px; border-radius: 50%; border: 1px solid rgba(255,255,255,.08); background: conic-gradient(from 210deg, #7dd3fc, #a78bfa, #22c55e, #7dd3fc); mask: radial-gradient(circle, transparent 58%, black 59%); }
    .knob::after { content: ""; position: absolute; width: 18px; height: 70px; border-radius: 99px; top: 34px; left: calc(50% - 9px); background: linear-gradient(#f8fbff, #76e4f7); box-shadow: 0 0 28px rgba(125,211,252,.85); }
    .pulse { animation: pulse .22s ease-out; }
    @keyframes pulse { 50% { filter: brightness(1.35); scale: 1.018; } }
    .mode { display: flex; gap: 10px; flex-wrap: wrap; margin: 22px 0; }
    button { border: 0; color: #dfe8ff; background: rgba(255,255,255,.08); border: 1px solid rgba(255,255,255,.14); padding: 14px 18px; border-radius: 18px; cursor: pointer; font-weight: 760; letter-spacing: -.01em; }
    button.active { background: linear-gradient(135deg, #38bdf8, #8b5cf6); color: white; box-shadow: 0 14px 35px rgba(88,124,255,.35); }
    .stat { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-top: 18px; }
    .stat div { border-radius: 18px; background: rgba(255,255,255,.06); padding: 16px; }
    .label { display: block; font-size: 12px; color: #8996bd; text-transform: uppercase; letter-spacing: .1em; margin-bottom: 8px; }
    .value { font-size: 22px; font-weight: 820; }
    .ok { color: #86efac; }
    .warn { color: #fbbf24; }
    code { color: #bfdbfe; }
    @media (max-width: 760px) { main { grid-template-columns: 1fr; } .knob-wrap { min-height: 340px; } .knob { width: 230px; } }
  </style>
</head>
<body>
  <main>
    <section class="card">
      <h1>KNOBController</h1>
      <p>Control visual del knob del teclado <code>MEETION</code>. Elige si el giro actúa como volumen o como scroll. La perilla se mueve en vivo cuando giras el knob físico.</p>
      <div class="mode">
        <button id="scroll" onclick="setMode('scroll')">Scroll vertical</button>
        <button id="volume" onclick="setMode('volume')">Volumen</button>
      </div>
      <span class="label">Clic del knob manda</span>
      <div class="mode" id="clickmap"></div>
      <div class="stat">
        <div><span class="label">Modo</span><span class="value" id="mode">...</span></div>
        <div><span class="label">Dirección</span><span class="value" id="dir">quieto</span></div>
        <div><span class="label">Ticks</span><span class="value" id="ticks">0</span></div>
      </div>
      <p id="status" class="warn">Conectando...</p>
    </section>
    <section class="card knob-wrap">
      <div class="knob" id="knob"></div>
    </section>
  </main>
  <script>
    let angle = 0;
    let ticks = 0;
    const knob = document.getElementById('knob');
    const modeEl = document.getElementById('mode');
    const dirEl = document.getElementById('dir');
    const ticksEl = document.getElementById('ticks');
    const statusEl = document.getElementById('status');
    const CLICK_LABELS = { mute: 'Silencio', enter: 'Enter', esc: 'Esc', tab: 'Tab', space: 'Espacio', playpause: 'Reproducir/Pausa' };
    const clickmapEl = document.getElementById('clickmap');
    function applyMode(mode) {
      modeEl.textContent = mode;
      document.getElementById('scroll').classList.toggle('active', mode === 'scroll');
      document.getElementById('volume').classList.toggle('active', mode === 'volume');
    }
    function applyClickKey(clickKey) {
      [...clickmapEl.children].forEach(btn => btn.classList.toggle('active', btn.dataset.key === clickKey));
    }
    async function setMode(mode) {
      const res = await fetch('/api/mode', { method: 'POST', headers: {'content-type':'application/json'}, body: JSON.stringify({mode}) });
      const data = await res.json();
      applyMode(data.mode);
    }
    async function setClickKey(clickKey) {
      const res = await fetch('/api/click-map', { method: 'POST', headers: {'content-type':'application/json'}, body: JSON.stringify({click_key: clickKey}) });
      const data = await res.json();
      applyClickKey(data.click_key);
    }
    async function loadStatus() {
      const res = await fetch('/api/status');
      const data = await res.json();
      applyMode(data.mode);
      clickmapEl.innerHTML = '';
      (data.click_keys || []).forEach(key => {
        const btn = document.createElement('button');
        btn.textContent = CLICK_LABELS[key] || key;
        btn.dataset.key = key;
        btn.onclick = () => setClickKey(key);
        clickmapEl.appendChild(btn);
      });
      applyClickKey(data.click_key);
      statusEl.textContent = data.device + ' activo';
      statusEl.className = 'ok';
    }
    function move(delta) {
      ticks += delta;
      angle += delta * 18;
      knob.style.setProperty('--angle', angle + 'deg');
      knob.classList.remove('pulse'); void knob.offsetWidth; knob.classList.add('pulse');
      dirEl.textContent = delta > 0 ? 'derecha / arriba' : 'izquierda / abajo';
      ticksEl.textContent = ticks;
    }
    loadStatus().catch(() => { statusEl.textContent = 'Servicio no disponible'; });
    const ev = new EventSource('/events');
    ev.onmessage = (msg) => {
      const data = JSON.parse(msg.data);
      if (data.type === 'mode') applyMode(data.mode);
      if (data.type === 'turn') move(data.delta);
      if (data.type === 'click_key') applyClickKey(data.click_key);
      if (data.type === 'click') {
        knob.classList.remove('pulse'); void knob.offsetWidth; knob.classList.add('pulse');
      }
    };
    ev.onerror = () => { statusEl.textContent = 'Reconectando al servicio...'; statusEl.className = 'warn'; };
  </script>
</body>
</html>
"""


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.mode = "scroll"
        self.click_key = DEFAULT_CLICK_KEY
        self.device = "not found"
        self.clients = []
        self.running = True

    def load(self):
        if CONFIG_PATH.exists():
            try:
                data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                self.mode = data.get("mode", "scroll") if data.get("mode") in {"scroll", "volume"} else "scroll"
                self.click_key = data.get("click_key") if data.get("click_key") in CLICK_KEYS else DEFAULT_CLICK_KEY
            except Exception:
                self.mode = "scroll"
                self.click_key = DEFAULT_CLICK_KEY
        else:
            self.save()

    def save(self):
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_PATH.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"mode": self.mode, "click_key": self.click_key}, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, CONFIG_PATH)

    def set_mode(self, mode):
        if mode not in {"scroll", "volume"}:
            raise ValueError("invalid mode")
        with self.lock:
            self.mode = mode
            self.save()
        self.publish({"type": "mode", "mode": mode})

    def set_click_key(self, click_key):
        if click_key not in CLICK_KEYS:
            raise ValueError("invalid click_key")
        with self.lock:
            self.click_key = click_key
            self.save()
        self.publish({"type": "click_key", "click_key": click_key})

    def publish(self, item):
        dead = []
        for client in list(self.clients):
            try:
                client.put_nowait(item)
            except Exception:
                dead.append(client)
        for client in dead:
            if client in self.clients:
                self.clients.remove(client)


state = State()


def resolve_source():
    data = Path("/proc/bus/input/devices").read_text(encoding="utf-8")
    for block in data.strip().split("\n\n"):
        if 'Name="Evision MEETION Keyboard"' not in block:
            continue
        if "REL=1040" not in block:
            continue
        for line in block.splitlines():
            if line.startswith("H: Handlers="):
                for token in line.split():
                    if token.startswith("event"):
                        return "/dev/input/" + token
    raise RuntimeError("MEETION knob event device not found")


def write_event(fd, ev_type, code, value):
    sec = int(time.time())
    usec = int((time.time() - sec) * 1_000_000)
    os.write(fd, struct.pack(EVENT, sec, usec, ev_type, code, value))


def create_uinput():
    mouse = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
    fcntl.ioctl(mouse, UI_SET_EVBIT, EV_REL)
    fcntl.ioctl(mouse, UI_SET_RELBIT, REL_WHEEL)
    mouse_dev = struct.pack("80sHHHHi" + "i" * 64 * 4, b"KNOBController scroll", BUS_USB, 0x320F, 0x5055, 1, 0, *([0] * 64 * 4))
    os.write(mouse, mouse_dev)
    fcntl.ioctl(mouse, UI_DEV_CREATE)

    keyboard = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
    fcntl.ioctl(keyboard, UI_SET_EVBIT, EV_KEY)
    fcntl.ioctl(keyboard, UI_SET_KEYBIT, KEY_VOLUMEUP)
    fcntl.ioctl(keyboard, UI_SET_KEYBIT, KEY_VOLUMEDOWN)
    # Todas las teclas que el clic del knob puede llegar a mandar: hay que
    # declarar la capacidad al crear el dispositivo uinput, no se puede
    # añadir después de UI_DEV_CREATE.
    for click_code in set(CLICK_KEYS.values()):
        fcntl.ioctl(keyboard, UI_SET_KEYBIT, click_code)
    keyboard_dev = struct.pack("80sHHHHi" + "i" * 64 * 4, b"KNOBController volume", BUS_USB, 0x320F, 0x5055, 1, 0, *([0] * 64 * 4))
    os.write(keyboard, keyboard_dev)
    fcntl.ioctl(keyboard, UI_DEV_CREATE)
    return mouse, keyboard


def emit_key(fd, key):
    write_event(fd, EV_KEY, key, 1)
    write_event(fd, EV_SYN, SYN_REPORT, 0)
    write_event(fd, EV_KEY, key, 0)
    write_event(fd, EV_SYN, SYN_REPORT, 0)


def knob_loop():
    source = None
    mouse = None
    keyboard = None
    while state.running:
        try:
            source_path = resolve_source()
            state.device = source_path
            source = os.open(source_path, os.O_RDONLY | os.O_NONBLOCK)
            mouse, keyboard = create_uinput()
            fcntl.ioctl(source, EVIOCGRAB, 1)
            print(f"KNOBController active: {source_path}", flush=True)
            while state.running:
                ready, _, _ = select.select([source], [], [], 0.5)
                if not ready:
                    continue
                data = os.read(source, EVENT_SIZE * 64)
                for idx in range(0, len(data) // EVENT_SIZE * EVENT_SIZE, EVENT_SIZE):
                    _sec, _usec, ev_type, code, value = struct.unpack(EVENT, data[idx : idx + EVENT_SIZE])
                    if ev_type != EV_KEY or value != 1:
                        continue
                    if code == KEY_KNOB_CLICK:
                        with state.lock:
                            click_key = state.click_key
                        emit_key(keyboard, CLICK_KEYS[click_key])
                        state.publish({"type": "click", "click_key": click_key})
                        continue
                    if code == KEY_VOLUMEUP:
                        delta = 1
                    elif code == KEY_VOLUMEDOWN:
                        delta = -1
                    else:
                        continue
                    with state.lock:
                        mode = state.mode
                    if mode == "scroll":
                        write_event(mouse, EV_REL, REL_WHEEL, delta)
                        write_event(mouse, EV_SYN, SYN_REPORT, 0)
                    else:
                        emit_key(keyboard, KEY_VOLUMEUP if delta > 0 else KEY_VOLUMEDOWN)
                    state.publish({"type": "turn", "delta": delta, "mode": mode})
        except Exception as exc:
            print(f"KNOBController loop error: {exc}", flush=True)
            time.sleep(2)
        finally:
            for fd, destroy in [(source, False), (mouse, True), (keyboard, True)]:
                if fd is None:
                    continue
                try:
                    if not destroy:
                        fcntl.ioctl(fd, EVIOCGRAB, 0)
                    else:
                        fcntl.ioctl(fd, UI_DEV_DESTROY)
                except Exception:
                    pass
                try:
                    os.close(fd)
                except Exception:
                    pass
            source = mouse = keyboard = None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, _format, *_args):
        return

    def send_json(self, data, status=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            body = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/status":
            self.send_json({
                "mode": state.mode,
                "device": state.device,
                "click_key": state.click_key,
                "click_keys": list(CLICK_KEYS.keys()),
            })
        elif self.path == "/events":
            client = queue.Queue(maxsize=128)
            state.clients.append(client)
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("cache-control", "no-cache")
            self.send_header("connection", "keep-alive")
            self.end_headers()
            try:
                self.wfile.write(f"data: {json.dumps({'type':'mode','mode':state.mode})}\n\n".encode("utf-8"))
                self.wfile.flush()
                while state.running:
                    # Sin item en 15s no significa que el cliente se fue —
                    # significa que el knob está quieto. Antes esto tiraba
                    # queue.Empty, el except lo trataba como error fatal y
                    # cortaba el stream: eso era el "Reconectando al
                    # servicio..." constante. Un comentario SSE (heartbeat)
                    # mantiene la conexión viva sin disparar onmessage.
                    try:
                        item = client.get(timeout=15)
                    except queue.Empty:
                        self.wfile.write(b": heartbeat\n\n")
                        self.wfile.flush()
                        continue
                    self.wfile.write(f"data: {json.dumps(item)}\n\n".encode("utf-8"))
                    self.wfile.flush()
            except Exception:
                if client in state.clients:
                    state.clients.remove(client)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("content-length", "0"))
        data = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/api/mode":
            try:
                state.set_mode(data.get("mode"))
                self.send_json({"mode": state.mode})
            except Exception as exc:
                self.send_json({"error": str(exc)}, 400)
        elif self.path == "/api/click-map":
            try:
                state.set_click_key(data.get("click_key"))
                self.send_json({"click_key": state.click_key})
            except Exception as exc:
                self.send_json({"error": str(exc)}, 400)
        else:
            self.send_response(404)
            self.end_headers()


def stop(_signum, _frame):
    state.running = False


def main():
    state.load()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    threading.Thread(target=knob_loop, daemon=True).start()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    # Sin esto, handle_request() bloquea indefinidamente esperando una
    # conexión NUEVA y nunca vuelve a mirar state.running — systemd mandaba
    # SIGTERM, nadie lo atendía a tiempo, y a los 10s SIGKILL (el servicio
    # quedaba en "failed" en vez de pararse limpio).
    server.timeout = 1.0
    print(f"KNOBController UI: http://{HOST}:{PORT}", flush=True)
    while state.running:
        server.handle_request()


if __name__ == "__main__":
    main()
