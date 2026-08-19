# KNOBController

**Your keyboard knob. Your rules.**

KNOBController is an open-source control layer for physical rotary inputs. It turns a keyboard knob into a programmable control surface instead of leaving it locked to one manufacturer-defined function.

The current production target is Linux. The tested MEETION knob can control vertical scroll, horizontal scroll, system volume, zoom, tab switching and configurable button gestures. v0.4 adds automatic per-application profiles on X11.

## What works now

### Rotary control

- Rotate left / right → vertical scroll.
- Rotate left / right → volume.
- `Ctrl + Knob` → zoom by default.
- `Shift + Knob` → horizontal scroll by default.
- `Alt + Knob` → tab switching by default.
- Modifier layers are configurable.

### Button gestures

- Click.
- Double click.
- Long press.
- Mappings: Mute, Enter, Esc, Tab, Space, Play/Pause or No-op.

### Per-app profiles — v0.4

An unprivileged desktop profile agent now detects the foreground X11 application and applies the corresponding KNOBController profile automatically.

Starter profiles:

```text
Global
Browser
Media
Video Editor
Design
IDE
```

Example behavior:

```text
Firefox / Chromium
  Knob          → Scroll
  Ctrl + Knob   → Zoom
  Shift + Knob  → Horizontal scroll
  Alt + Knob    → Tabs

Spotify / VLC / mpv
  Knob          → Volume
  Click         → Play / Pause
  Double Click  → Mute

Video editor
  Knob          → Scroll / navigation
  Ctrl + Knob   → Zoom
  Shift + Knob  → Horizontal navigation
  Click         → Space

IDE
  Knob          → Scroll
  Ctrl + Knob   → Zoom
  Alt + Knob    → Tabs
```

Profiles live in:

```text
~/.config/knob-controller/profiles.json
```

See [`docs/PROFILES.md`](docs/PROFILES.md).

## Architecture

KNOBController separates privileged hardware access from desktop context.

```text
                    KNOBController v0.4

Desktop session                         Hardware layer
────────────────                        ──────────────
foreground app
      ↓
Profile Agent (user)
      ↓ localhost API
      ├──────────────────────────────→ Linux daemon
      │                                  ↓
      │                              Gesture Engine
      │                                  ↓
      │                              Action Engine
      │                                  ↓
      │                            LinuxActionExecutor
      │                                  ↓
      │                          evdev / /dev/uinput
      │                                  ↓
      └──────────────────────────── physical knob
```

The product core is still platform-oriented:

```text
physical rotary input
        ↓
device adapter
        ↓
gesture engine
        ↓
context / active profile
        ↓
action engine
        ↓
OS backend
```

## Local APIs

### Hardware daemon

```text
http://127.0.0.1:8766
```

Current endpoints include:

```text
GET  /api/status
GET  /api/profiles
POST /api/mode
POST /api/click-map
POST /api/gesture-map
POST /api/modifier-map
GET  /events
```

### Profile agent

```text
http://127.0.0.1:8767
```

Read-only runtime endpoints:

```text
GET /api/status
GET /api/profiles
GET /events
```

## Linux session support

### X11

Automatic foreground-application switching is implemented using the EWMH `_NET_ACTIVE_WINDOW` hint through `xprop`. The profile agent belongs to the user session and does not run as root.

### Wayland

Wayland is detected explicitly. Automatic foreground-app switching is not claimed as finished yet because there is no single universal cross-compositor foreground-window API. On Wayland, KNOBController safely falls back to the Global profile.

## Device support

Current tested hardware:

- Evision / MEETION keyboard rotary interface used during development.

The architecture is moving toward device adapters and generic HID discovery. MEETION is the first supported device family, not the intended product boundary.

## Repository map

```text
.
├── knob_controller_daemon.py          # v0.3+ Linux hardware daemon
├── knob_engine.py                     # platform-independent gesture/action engine
├── linux_backend.py                   # uinput action execution
├── modifier_input.py                  # Ctrl/Shift/Alt state tracking
├── app_context.py                     # foreground-app detection + matching
├── knob-controller-agent.py           # v0.4 unprivileged per-app profile agent
├── knob-controller.service            # hardware daemon service
├── knob-controller-agent.service      # systemd user profile-agent service
├── test_linux_backend.py
├── test_modifier_layers.py
├── test_app_context.py
├── tests/
│   └── test_knob_engine.py
├── docs/
│   └── PROFILES.md
└── native-app/
    └── tauri/
        ├── ui-v2/                     # hardware-inspired desktop UI
        └── src-tauri/
```

Legacy v0.x files remain in the repository during migration so existing installations are not silently broken.

## Desktop UI

The Tauri interface is intentionally inspired by physical audio control surfaces rather than generic dashboard UI.

Product rule:

1. Real functions look active.
2. Future functions are visibly marked as Next/Roadmap.
3. No fake battery, firmware, haptics or device telemetry is presented.

## Platform direction

### Linux

```text
evdev → KNOBController engine → uinput
```

Current production target.

### Windows

Planned:

```text
Raw Input / HID → KNOBController engine → SendInput / native output backend
```

### macOS

Planned:

```text
IOKit / HID → KNOBController engine → macOS input backend
```

The Linux daemon cannot simply be repackaged unchanged for Windows or macOS because evdev and `/dev/uinput` are Linux-specific.

## Road to v1.0

Major remaining milestones:

- Generic HID / device-adapter discovery.
- Wayland foreground-app backends.
- UI editor for creating and ordering profiles without editing JSON.
- Packaged Linux installer and clean privilege setup.
- Automatic builds and versioned GitHub Releases.
- Supported-device matrix.
- Windows backend.
- macOS backend.
- Screenshots and demo video/GIF.
- `CHANGELOG.md`, `CONTRIBUTING.md`, `SECURITY.md` and issue templates.

## License

KNOBController is open-source software from Edge Marketing Agency / EMA. See `LICENSE`.

**KNOBController — Turn any keyboard knob into a control surface.**
