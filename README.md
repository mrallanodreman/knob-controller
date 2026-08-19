# KNOBController

**Your keyboard knob. Your rules.**

KNOBController is an open-source control layer for physical rotary inputs. It turns a keyboard knob into a programmable control surface instead of leaving it locked to one manufacturer-defined function.

The current production target is Linux. The project now supports a tested MEETION rotary interface, modifier layers, per-application profiles, a visual profile editor, device discovery, persistent calibrated adapters, and v0.8 runtime decoding for both `EV_KEY` and `EV_REL` rotation patterns.

## What works now

### Rotary control

- Vertical scroll.
- Horizontal scroll.
- System volume.
- `Ctrl + Knob` → zoom by default.
- `Shift + Knob` → horizontal scroll by default.
- `Alt + Knob` → tab switching by default.
- Modifier layers are configurable.

### Button gestures

- Click.
- Double click.
- Long press.
- Mappings: Mute, Enter, Esc, Tab, Space, Play/Pause or No-op.

### Per-app profiles

An unprivileged desktop profile agent detects the foreground X11 application and applies the corresponding profile automatically.

Starter profiles:

```text
Global
Browser
Media
Video Editor
Design
IDE
```

Profiles can be created and edited visually from the Tauri Profile Editor. The runtime configuration lives in:

```text
~/.config/knob-controller/profiles.json
```

See [`docs/PROFILES.md`](docs/PROFILES.md).

### Device discovery and calibration

The Linux daemon now discovers rotary candidates through a device-adapter registry instead of hard-coding one event node.

Built-in adapter types:

```text
meetion
calibrated
generic-hid candidate scanner
```

Unknown candidates are not auto-grabbed. They can be learned through the visual Device Calibration flow:

```text
select candidate
    ↓
TURN LEFT
    ↓
TURN RIGHT
    ↓
PRESS KNOB
    ↓
validate event map
    ↓
save calibrated adapter
```

v0.8 supports two learned runtime layouts:

```text
EV_KEY left/right + EV_KEY press
EV_REL left/right + EV_KEY press
```

For relative axes, KNOBController persists the learned event value/sign so accelerated values still resolve to the correct direction.

Calibrated device profiles live in:

```text
/etc/knob-controller/devices.json
```

See [`docs/DEVICES.md`](docs/DEVICES.md) and [`docs/CALIBRATION.md`](docs/CALIBRATION.md).

## Architecture

KNOBController separates privileged hardware access from desktop context.

```text
Desktop session                         Hardware layer
────────────────                        ──────────────
foreground app
      ↓
Profile Agent (user)
      ↓ localhost API
      ├──────────────────────────────→ Linux daemon
      │                                  ↓
      │                             Device Registry
      │                                  ↓
      │                           Runtime Event Decoder
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

The portable product model remains:

```text
physical rotary input
        ↓
device adapter
        ↓
normalized input decoder
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
GET  /api/devices
GET  /api/calibration
POST /api/mode
POST /api/click-map
POST /api/gesture-map
POST /api/modifier-map
POST /api/calibration/start
POST /api/calibration/arm
POST /api/calibration/cancel
POST /api/calibration/save
GET  /events
```

### Profile agent

```text
http://127.0.0.1:8767
```

The profile agent exposes profile/runtime state and write operations used by the visual editor.

## Linux session support

### X11

Automatic foreground-application switching is implemented using the EWMH `_NET_ACTIVE_WINDOW` hint through `xprop`. The profile agent belongs to the user session and does not run as root.

### Wayland

Wayland is detected explicitly. Automatic foreground-app switching is not claimed as finished yet because there is no single universal cross-compositor foreground-window API. On Wayland, KNOBController safely falls back to the Global profile.

## Device support

Confirmed development hardware:

- Evision / MEETION keyboard rotary interface.

Additional Linux rotary devices can now be surfaced as candidates and, when their evdev layout fits the supported decoder model, calibrated without adding a handwritten adapter.

## Desktop UI

The Tauri interface is intentionally inspired by physical audio control surfaces rather than generic dashboard UI.

Current windows:

```text
Main Control Surface
Profile Editor
Device Calibration
```

Product rule:

1. Real functions look active.
2. Future functions are visibly marked as Next/Roadmap.
3. No fake battery, firmware, haptics or device telemetry is presented.

## Repository map

```text
.
├── knob_controller_daemon.py          # proven Linux hardware/action runtime
├── knob_controller_daemon_v06.py      # adapter-aware discovery layer
├── knob_controller_daemon_v07.py      # interactive calibration API
├── knob_controller_daemon_v08.py      # EV_REL runtime + v0.8 integration
├── knob_engine.py                     # platform-independent gesture/action engine
├── linux_backend.py                   # uinput action execution
├── modifier_input.py                  # Ctrl/Shift/Alt state tracking
├── app_context.py                     # foreground-app detection + matching
├── knob-controller-agent.py           # unprivileged per-app profile agent
├── devices/
│   ├── base.py
│   ├── registry.py
│   ├── meetion.py
│   ├── generic_hid.py
│   ├── custom.py
│   ├── calibration.py
│   └── decoder.py
├── docs/
│   ├── PROFILES.md
│   ├── DEVICES.md
│   └── CALIBRATION.md
└── native-app/tauri/
    ├── ui-v2/
    │   ├── index.html
    │   ├── profiles.html
    │   └── calibration.html
    └── src-tauri/
```

Legacy v0.x files remain in the repository during migration so existing installations are not silently broken.

## Platform direction

### Linux

```text
evdev → device decoder → KNOBController engine → uinput
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

- Wayland foreground-app backends.
- Clean Linux installer and privilege setup.
- Consolidation of migration wrappers into one production daemon entrypoint.
- Automatic builds and versioned GitHub Releases.
- Supported-device matrix.
- More device-family adapters and calibration fixtures.
- Windows backend.
- macOS backend.
- Screenshots and demo video/GIF.
- `CHANGELOG.md`, `CONTRIBUTING.md`, `SECURITY.md` and issue templates.

## License

KNOBController is open-source software from Edge Marketing Agency / EMA. See `LICENSE`.

**KNOBController — Turn any keyboard knob into a control surface.**
