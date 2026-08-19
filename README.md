# KNOBController

**Your keyboard knob. Your rules.**

KNOBController is an open-source control layer for rotary inputs. It turns the physical knob on a supported keyboard into a programmable control surface instead of leaving it locked to one manufacturer-defined function.

The current Linux backend is already functional with the tested MEETION keyboard: rotation can control **vertical scrolling** or **system volume**, and the knob press can be remapped to **Mute, Enter, Esc, Tab, Space or Play/Pause**.

The product direction is broader: generic rotary-device discovery, application-aware profiles, gesture combinations, creative-tool controls, and native Windows/macOS backends.

## Current status

### Available now

- Linux backend using `evdev`.
- Virtual input injection through `/dev/uinput`.
- Automatic detection of the tested `Evision MEETION Keyboard` knob event interface.
- Exclusive grab of the physical rotary input while KNOBController is active.
- Rotate right / left -> vertical scroll.
- Rotate right / left -> volume up / down.
- Knob click remapping:
  - Mute
  - Enter
  - Esc
  - Tab
  - Space
  - Play/Pause
- Persistent configuration in `/etc/knob-controller/config.json`.
- Local HTTP API at `127.0.0.1:8766`.
- Server-Sent Events stream for live knob activity.
- Native GTK client.
- Tauri desktop shell with a hardware-inspired control-surface UI.
- systemd service files and desktop launchers.

### Product roadmap

The interface already reserves clear space for the next capabilities without presenting them as finished features:

- Horizontal scroll.
- Zoom.
- Tab switching.
- Timeline scrubbing for video editors.
- Brush-size control for creative applications.
- Workspace switching.
- Double-click gesture.
- Long-press gesture.
- `Shift + knob`, `Ctrl + knob`, and `Alt + knob` layers.
- Per-application profiles.
- Automatic profile switching by foreground application.
- Multiple rotary devices.
- Generic HID discovery.
- Device adapters instead of a MEETION-only detector.
- Windows Raw HID / SendInput backend.
- macOS IOKit / HID backend.

## Product model

KNOBController is intentionally not designed as a generic keyboard remapper. The architecture is evolving around one specific concept:

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

This allows the same physical knob to behave differently depending on context.

Example target behavior:

```text
Browser
  Rotate       -> vertical scroll
  Ctrl+Rotate  -> zoom
  Click        -> middle click

Music player
  Rotate       -> volume
  Click        -> play/pause

Video editor
  Rotate       -> timeline scrub
  Shift+Rotate -> timeline zoom

Image editor
  Rotate       -> brush size
  Ctrl+Rotate  -> zoom

IDE
  Rotate       -> scroll
  Ctrl+Rotate  -> zoom
  Alt+Rotate   -> tabs
```

## Architecture today

```text
MEETION keyboard knob
        ↓
Linux evdev
        ↓
knob-controller.py
        ↓
┌──────────────────────┐
│ state + config       │
│ local HTTP API       │
│ SSE live events      │
└──────────────────────┘
        ↓
/dev/uinput
        ↓
scroll / volume / key action
```

The Tauri UI talks to the daemon at:

```text
http://127.0.0.1:8766
```

Current endpoints:

```text
GET  /api/status
POST /api/mode
POST /api/click-map
GET  /events
```

## UI philosophy

The desktop interface is inspired by physical audio control surfaces rather than generic dashboard UI.

The design has two strict rules:

1. **Real functions look active.** Scroll, volume, current click mapping, device status and live activity are wired to the daemon.
2. **Future functions are visible but explicitly marked as Roadmap / Next.** The interface does not invent firmware, battery, haptics or unsupported device telemetry.

This gives contributors a concrete visual target while keeping the current product honest.

## Repository map

```text
.
├── knob-controller.py                 # Linux daemon + current web control UI
├── knob-controller-agent.py           # local agent
├── knob-controller.service            # systemd daemon service
├── knob-controller-agent.service      # systemd agent service
├── knob-controller.desktop            # desktop launcher
├── knob-controller-open.sh            # browser/control launcher
└── native-app/
    ├── knob-controller-native.py       # native GTK client
    ├── knob-controller-native.desktop
    ├── knob-controller-native-open.sh
    └── tauri/
        ├── ui/index.html               # product desktop UI
        └── src-tauri/                  # Tauri shell
```

## Platform direction

### Linux

Current production target.

```text
evdev -> KNOBController engine -> uinput
```

### Windows

Planned native backend.

```text
Raw HID / Windows input APIs -> KNOBController engine -> SendInput
```

### macOS

Planned native backend.

```text
IOKit / HID -> KNOBController engine -> macOS input APIs
```

The Linux daemon cannot simply be packaged unchanged for Microsoft Store or Mac App Store because `evdev` and `/dev/uinput` are Linux-specific.

## Public-release targets

Before `v1.0.0`, the project should have:

- device-adapter abstraction;
- first generic HID discovery path;
- action/gesture model separated from device handling;
- packaged Linux installer;
- automated builds in GitHub Actions;
- versioned GitHub Releases;
- checksums;
- supported-device matrix;
- screenshots and demo video/GIF;
- `CHANGELOG.md`;
- `CONTRIBUTING.md`;
- `SECURITY.md`;
- issue templates;
- Windows backend milestone defined and tracked.

## License

KNOBController is open-source software from Edge Marketing Agency / EMA. See `LICENSE` for the repository license.

Project: **KNOBController**  
Product line: **Turn any keyboard knob into a control surface.**
