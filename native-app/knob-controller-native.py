#!/usr/bin/env python3
import http.client
import json
import math
import os
import subprocess
import threading
import time
import urllib.request

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk


API = "http://127.0.0.1:8766"

# EMA distribuye esta app como software libre para hacerse publicidad — el
# logo real va en la cabecera y en el pie, no un icono genérico.
ASSET_DIR = os.environ.get("KNOB_ASSET_DIR", "/usr/local/share/knob-controller/assets")
EMA_MARK = os.path.join(ASSET_DIR, "ema-mark.png")
EMA_LOGO = os.path.join(ASSET_DIR, "ema-logo-white.png")


def load_pixbuf(path, width):
    """Carga un PNG y lo escala a `width` de ancho manteniendo proporción.
    Si el asset no está instalado, devuelve None — quien llame decide el
    respaldo, la app nunca debe caerse por falta de un logo."""
    try:
        pix = GdkPixbuf.Pixbuf.new_from_file(path)
        ratio = pix.get_height() / pix.get_width()
        return pix.scale_simple(width, round(width * ratio), GdkPixbuf.InterpType.BILINEAR)
    except Exception:
        return None

CLICK_LABELS = {
    "mute": "Silencio",
    "enter": "Enter",
    "esc": "Esc",
    "tab": "Tab",
    "space": "Espacio",
    "playpause": "Reproducir / Pausa",
}


class Knob(Gtk.DrawingArea):
    """Perilla dibujada a mano: arco de progreso, aguja con glow, y un
    anillo de choque (ripple) que se expande y se apaga al recibir un clic
    físico — distinto del pulso de giro, para que se sientan como dos
    gestos distintos."""

    def __init__(self):
        super().__init__()
        self.angle = 0.0
        self.pulse_until = 0.0
        self.ripple_started = None
        self.set_size_request(340, 340)

    def turn(self, delta):
        self.angle += delta * 18
        self.pulse_until = time.time() + 0.22
        self.queue_draw()

    def click(self):
        self.ripple_started = time.time()
        self.queue_draw()

    def do_draw(self, cr):
        alloc = self.get_allocation()
        w, h = alloc.width, alloc.height
        cx, cy = w / 2, h / 2
        r = min(w, h) * 0.40
        pulse = 1.035 if time.time() < self.pulse_until else 1.0
        now = time.time()

        cr.save()
        cr.translate(cx, cy)

        # Halo ambiente detrás de la esfera: respira suave, da sensación de
        # "encendido" en vez de un disco plano flotando en la nada.
        breathe = 0.5 + 0.5 * math.sin(now * 1.3)
        halo = self._radial(0, 0, r * 1.85)
        halo.add_color_stop_rgba(0.0, 0.35, 0.55, 1.0, 0.14 + 0.05 * breathe)
        halo.add_color_stop_rgba(1.0, 0.35, 0.55, 1.0, 0.0)
        cr.set_source(halo)
        cr.arc(0, 0, r * 1.85, 0, math.tau)
        cr.fill()

        # Anillo de choque del clic: se expande y se desvanece en ~500ms.
        if self.ripple_started is not None:
            t = now - self.ripple_started
            if t < 0.5:
                k = t / 0.5
                cr.set_line_width(4 * (1 - k))
                cr.set_source_rgba(0.55, 0.85, 1.0, 0.9 * (1 - k))
                cr.arc(0, 0, r * (1.02 + 0.45 * k), 0, math.tau)
                cr.stroke()
                GLib.timeout_add(16, self._redraw_if_rippling)
            else:
                self.ripple_started = None

        cr.scale(pulse, pulse)

        grad = self._radial(-r * 0.32, -r * 0.38, r * 1.5)
        grad.add_color_stop_rgb(0.0, 0.22, 0.27, 0.50)
        grad.add_color_stop_rgb(0.55, 0.10, 0.12, 0.22)
        grad.add_color_stop_rgb(1.0, 0.02, 0.03, 0.06)
        cr.set_source(grad)
        cr.arc(0, 0, r, 0, math.tau)
        cr.fill()

        cr.set_source_rgba(1, 1, 1, 0.06)
        cr.set_line_width(1.4)
        cr.arc(0, 0, r - 2, 0, math.tau)
        cr.stroke()

        cr.set_line_width(11)
        cr.set_line_cap(1)
        for i, color in enumerate([(0.49, 0.83, 0.98), (0.36, 0.58, 0.98), (0.13, 0.77, 0.37)]):
            cr.set_source_rgba(*color, 0.78)
            cr.arc(0, 0, r - 30 - i * 7, math.radians(215 + i * 55), math.radians(295 + i * 55))
            cr.stroke()

        # Centro: disco chico con el mismo lenguaje visual, ancla la aguja.
        hub = self._radial(-4, -4, 26)
        hub.add_color_stop_rgb(0.0, 0.30, 0.36, 0.58)
        hub.add_color_stop_rgb(1.0, 0.06, 0.07, 0.12)
        cr.set_source(hub)
        cr.arc(0, 0, r * 0.16, 0, math.tau)
        cr.fill()

        cr.rotate(math.radians(self.angle))
        pointer = self._linear(0, -r * 0.82, 0, -r * 0.30)
        pointer.add_color_stop_rgb(0.0, 0.97, 0.99, 1.0)
        pointer.add_color_stop_rgb(1.0, 0.46, 0.89, 0.97)
        cr.set_source(pointer)
        self._rounded_rect(cr, -8, -r * 0.80, 16, r * 0.32, 8)
        cr.fill()
        cr.restore()

        if time.time() < self.pulse_until:
            GLib.timeout_add(30, self._redraw_if_pulsing)
        return False

    def _redraw_if_pulsing(self):
        self.queue_draw()
        return time.time() < self.pulse_until

    def _redraw_if_rippling(self):
        self.queue_draw()
        return self.ripple_started is not None

    def _radial(self, x, y, r):
        import cairo

        return cairo.RadialGradient(x, y, 0, 0, 0, r)

    def _linear(self, x0, y0, x1, y1):
        import cairo

        return cairo.LinearGradient(x0, y0, x1, y1)

    def _rounded_rect(self, cr, x, y, w, h, radius):
        cr.new_sub_path()
        cr.arc(x + w - radius, y + radius, radius, -math.pi / 2, 0)
        cr.arc(x + w - radius, y + h - radius, radius, 0, math.pi / 2)
        cr.arc(x + radius, y + h - radius, radius, math.pi / 2, math.pi)
        cr.arc(x + radius, y + radius, radius, math.pi, 3 * math.pi / 2)
        cr.close_path()


class Mark(Gtk.DrawingArea):
    """Marca pequeña junto al título: un mini-knob, mismo lenguaje visual
    que la perilla grande, para que la cabecera no sea solo texto plano."""

    def __init__(self):
        super().__init__()
        self.set_size_request(40, 40)

    def do_draw(self, cr):
        alloc = self.get_allocation()
        cx, cy = alloc.width / 2, alloc.height / 2
        r = min(alloc.width, alloc.height) * 0.46
        cr.save()
        cr.translate(cx, cy)
        import cairo

        grad = cairo.RadialGradient(-r * 0.3, -r * 0.3, 0, 0, 0, r * 1.4)
        grad.add_color_stop_rgb(0.0, 0.30, 0.55, 0.95)
        grad.add_color_stop_rgb(1.0, 0.10, 0.13, 0.30)
        cr.set_source(grad)
        cr.arc(0, 0, r, 0, math.tau)
        cr.fill()
        cr.set_line_width(3)
        cr.set_source_rgba(0.97, 0.99, 1.0, 0.95)
        cr.move_to(0, -r * 0.05)
        cr.line_to(0, -r * 0.68)
        cr.stroke()
        cr.restore()
        return False


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="art.edgemarketing.KNOBController")
        self.mode = "scroll"
        self.click_key = "mute"
        self.click_keys = list(CLICK_LABELS.keys())
        self.ticks = 0
        self.last_click_label = "—"
        self.click_buttons = {}

    def do_activate(self):
        self._ensure_service()
        self.window = Gtk.ApplicationWindow(application=self)
        self.window.set_title("KNOBController")
        self.window.set_default_size(1040, 640)
        self.window.set_position(Gtk.WindowPosition.CENTER)
        self.window.connect("delete-event", self.on_close)

        css = Gtk.CssProvider()
        css.load_from_data(b"""
        window { background-image: radial-gradient(circle at 20% -10%, #1c2440, #05060c 68%); }
        .card {
          background: rgba(11,14,26,0.82);
          border-radius: 26px;
          border: 1px solid rgba(140,165,255,0.16);
          padding: 30px;
        }
        .title { color: #f3f6ff; font-size: 40px; font-weight: 900; letter-spacing: -0.02em; }
        .kicker { color: #7c8ad1; font-size: 11px; font-weight: 800; letter-spacing: 0.22em; }
        .copy { color: #99a3c9; font-size: 15px; }
        .section-label { color: #7c8ad1; font-size: 11px; font-weight: 800; letter-spacing: 0.14em; margin-top: 4px; }
        .stat-label { color: #7c8ad1; font-size: 10px; font-weight: 700; letter-spacing: 0.12em; }
        .stat-value { color: #f3f6ff; font-size: 21px; font-weight: 900; }
        .stat-box { background: rgba(255,255,255,0.045); border: 1px solid rgba(255,255,255,0.06); border-radius: 16px; padding: 13px 14px; }
        .status-row { color: #99a3c9; font-size: 13px; }
        .credit { color: #5c6690; font-size: 11px; }
        .dot { font-size: 13px; }
        .dot-ok { color: #4ade80; }
        .dot-warn { color: #fbbf24; }
        button.pill {
          border-radius: 999px;
          padding: 11px 18px;
          background: rgba(255,255,255,0.055);
          color: #cdd6f4;
          border: 1px solid rgba(255,255,255,0.10);
          font-weight: 700;
          font-size: 13px;
        }
        button.pill:hover { background: rgba(255,255,255,0.10); }
        button.pill.active {
          background-image: linear-gradient(135deg, #38bdf8, #2563eb);
          color: white;
          border-color: rgba(255,255,255,0.25);
        }
        button.pill.small { padding: 8px 14px; font-size: 12px; }
        separator { background: rgba(255,255,255,0.08); min-height: 1px; }
        """)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=24)
        root.set_margin_top(24)
        root.set_margin_bottom(24)
        root.set_margin_start(24)
        root.set_margin_end(24)
        self.window.add(root)

        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        left.get_style_context().add_class("card")
        left.set_hexpand(True)
        left.set_vexpand(True)
        root.pack_start(left, True, True, 0)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        mark_pix = load_pixbuf(EMA_MARK, 40)
        header.pack_start(Gtk.Image.new_from_pixbuf(mark_pix) if mark_pix else Mark(), False, False, 0)
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        kicker = Gtk.Label(label="TECLADO MEETION", xalign=0)
        kicker.get_style_context().add_class("kicker")
        title = Gtk.Label(label="KNOBController", xalign=0)
        title.get_style_context().add_class("title")
        title_box.pack_start(kicker, False, False, 0)
        title_box.pack_start(title, False, False, 0)
        header.pack_start(title_box, False, False, 0)
        left.pack_start(header, False, False, 0)

        copy = Gtk.Label(
            label="Elige qué hace el giro y qué manda el clic. Los cambios se aplican al instante, sin reiniciar nada.",
            xalign=0,
        )
        copy.set_line_wrap(True)
        copy.get_style_context().add_class("copy")
        left.pack_start(copy, False, False, 0)

        left.pack_start(self._section_label("GIRO"), False, False, 0)
        mode_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.scroll_btn = self._pill("Scroll vertical", lambda _b: self.set_mode("scroll"))
        self.volume_btn = self._pill("Volumen", lambda _b: self.set_mode("volume"))
        mode_row.pack_start(self.scroll_btn, False, False, 0)
        mode_row.pack_start(self.volume_btn, False, False, 0)
        left.pack_start(mode_row, False, False, 0)

        left.pack_start(self._section_label("CLIC DEL KNOB MANDA"), False, False, 0)
        click_row = Gtk.FlowBox()
        click_row.set_selection_mode(Gtk.SelectionMode.NONE)
        click_row.set_max_children_per_line(6)
        click_row.set_row_spacing(8)
        click_row.set_column_spacing(8)
        for key in self.click_keys:
            btn = self._pill(CLICK_LABELS.get(key, key), self._click_handler(key), small=True)
            self.click_buttons[key] = btn
            click_row.insert(btn, -1)
        left.pack_start(click_row, False, False, 0)

        left.pack_start(Gtk.Separator(), False, False, 6)

        stats = Gtk.Grid(column_spacing=10, row_spacing=8)
        stats.set_column_homogeneous(True)
        self.mode_value = self._stat(stats, 0, "MODO", "...")
        self.dir_value = self._stat(stats, 1, "GIRO", "quieto")
        self.ticks_value = self._stat(stats, 2, "TICKS", "0")
        self.click_value = self._stat(stats, 3, "ÚLTIMO CLIC", "—")
        left.pack_start(stats, False, False, 0)

        status_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.status_dot = Gtk.Label(label="●")
        self.status_dot.get_style_context().add_class("dot")
        self.status_dot.get_style_context().add_class("dot-warn")
        self.status_label = Gtk.Label(label="Conectando...", xalign=0)
        self.status_label.get_style_context().add_class("status-row")
        status_row.pack_start(self.status_dot, False, False, 0)
        status_row.pack_start(self.status_label, False, False, 0)
        left.pack_start(status_row, False, False, 4)

        close_btn = self._pill("Aplicar y cerrar", lambda _b: self.close_cleanly())
        left.pack_start(close_btn, False, False, 0)

        left.pack_start(Gtk.Box(), True, True, 0)
        left.pack_start(Gtk.Separator(), False, False, 0)
        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        footer.set_margin_top(4)
        logo_pix = load_pixbuf(EMA_LOGO, 84)
        if logo_pix:
            footer.pack_start(Gtk.Image.new_from_pixbuf(logo_pix), False, False, 0)
        credit = Gtk.Label(label="Software libre por Edge Marketing Agency — edgemarketing.art", xalign=0)
        credit.get_style_context().add_class("credit")
        footer.pack_start(credit, False, False, 0)
        left.pack_start(footer, False, False, 0)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        right.get_style_context().add_class("card")
        right.set_hexpand(True)
        right.set_vexpand(True)
        root.pack_start(right, True, True, 0)

        self.knob = Knob()
        right.pack_start(Gtk.Box(), True, True, 0)
        right.pack_start(self.knob, False, False, 0)
        right.pack_start(Gtk.Box(), True, True, 0)

        self.window.show_all()
        self.refresh_status()
        threading.Thread(target=self.event_loop, daemon=True).start()

    def _section_label(self, text):
        lab = Gtk.Label(label=text, xalign=0)
        lab.get_style_context().add_class("section-label")
        return lab

    def _pill(self, label, handler, small=False):
        btn = Gtk.Button(label=label)
        ctx = btn.get_style_context()
        ctx.add_class("pill")
        if small:
            ctx.add_class("small")
        btn.connect("clicked", handler)
        return btn

    def _click_handler(self, key):
        return lambda _btn: self.set_click_key(key)

    def _stat(self, grid, col, label, value):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.get_style_context().add_class("stat-box")
        lab = Gtk.Label(label=label, xalign=0)
        lab.get_style_context().add_class("stat-label")
        val = Gtk.Label(label=value, xalign=0)
        val.get_style_context().add_class("stat-value")
        box.pack_start(lab, False, False, 0)
        box.pack_start(val, False, False, 0)
        grid.attach(box, col, 0, 1, 1)
        return val

    def _ensure_service(self):
        subprocess.run(["sudo", "systemctl", "start", "knob-controller.service"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)

    def on_close(self, *_args):
        self.close_cleanly()
        return True

    def close_cleanly(self):
        if self.mode == "volume":
            # El volumen es el comportamiento nativo del hardware: sin
            # demonio agarrando el dispositivo, las teclas de verdad llegan
            # solas, no hace falta nada corriendo.
            subprocess.run(["sudo", "systemctl", "stop", "knob-controller.service"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        self.quit()

    def refresh_status(self):
        try:
            data = json.loads(urllib.request.urlopen(API + "/api/status", timeout=2).read())
            self.apply_mode(data.get("mode", "scroll"))
            keys = data.get("click_keys") or self.click_keys
            if keys != self.click_keys:
                self.click_keys = keys
            self.apply_click_key(data.get("click_key", "mute"))
            self.status_label.set_text(data.get("device", "dispositivo") + " activo")
            self.status_dot.get_style_context().remove_class("dot-warn")
            self.status_dot.get_style_context().add_class("dot-ok")
        except Exception:
            self.status_label.set_text("Servicio no disponible")
            self.status_dot.get_style_context().remove_class("dot-ok")
            self.status_dot.get_style_context().add_class("dot-warn")
        return False

    def set_mode(self, mode):
        req = urllib.request.Request(API + "/api/mode", data=json.dumps({"mode": mode}).encode(), headers={"content-type": "application/json"}, method="POST")
        try:
            data = json.loads(urllib.request.urlopen(req, timeout=2).read())
            self.apply_mode(data.get("mode", mode))
        except Exception as exc:
            self.status_label.set_text("No se pudo cambiar modo: " + str(exc))

    def set_click_key(self, key):
        req = urllib.request.Request(API + "/api/click-map", data=json.dumps({"click_key": key}).encode(), headers={"content-type": "application/json"}, method="POST")
        try:
            data = json.loads(urllib.request.urlopen(req, timeout=2).read())
            self.apply_click_key(data.get("click_key", key))
        except Exception as exc:
            self.status_label.set_text("No se pudo cambiar el clic: " + str(exc))

    def apply_mode(self, mode):
        self.mode = mode
        self.mode_value.set_text(mode)
        self.scroll_btn.get_style_context().remove_class("active")
        self.volume_btn.get_style_context().remove_class("active")
        if mode == "scroll":
            self.scroll_btn.get_style_context().add_class("active")
        else:
            self.volume_btn.get_style_context().add_class("active")

    def apply_click_key(self, key):
        self.click_key = key
        for k, btn in self.click_buttons.items():
            btn.get_style_context().remove_class("active")
        if key in self.click_buttons:
            self.click_buttons[key].get_style_context().add_class("active")

    def apply_turn(self, delta):
        self.ticks += delta
        self.ticks_value.set_text(str(self.ticks))
        self.dir_value.set_text("derecha / arriba" if delta > 0 else "izquierda / abajo")
        self.knob.turn(delta)

    def apply_click_event(self, key):
        self.last_click_label = CLICK_LABELS.get(key, key)
        self.click_value.set_text(self.last_click_label)
        self.knob.click()

    def event_loop(self):
        while True:
            try:
                conn = http.client.HTTPConnection("127.0.0.1", 8766, timeout=30)
                conn.request("GET", "/events")
                resp = conn.getresponse()
                while resp.status == 200:
                    line = resp.readline().decode("utf-8", "replace").strip()
                    if not line.startswith("data: "):
                        continue
                    data = json.loads(line[6:])
                    kind = data.get("type")
                    if kind == "mode":
                        GLib.idle_add(self.apply_mode, data.get("mode", "scroll"))
                    elif kind == "turn":
                        GLib.idle_add(self.apply_turn, int(data.get("delta", 0)))
                    elif kind == "click_key":
                        GLib.idle_add(self.apply_click_key, data.get("click_key", "mute"))
                    elif kind == "click":
                        GLib.idle_add(self.apply_click_event, data.get("click_key", "mute"))
                GLib.idle_add(self.status_label.set_text, "Reconectando al servicio...")
            except Exception:
                GLib.idle_add(self.status_label.set_text, "Reconectando al servicio...")
                time.sleep(1)


if __name__ == "__main__":
    App().run(None)
