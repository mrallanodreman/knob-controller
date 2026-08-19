# KNOBController

**Your keyboard knob. Your rules.**

KNOBController is an open-source control layer for rotary inputs. It turns the physical knob on a supported keyboard into a programmable control surface instead of leaving it locked to one manufacturer-defined function.

The current Linux implementation is functional with the tested `Evision MEETION Keyboard`. KNOBController can already route the physical knob through a gesture/action engine, change its base behavior between **vertical scroll** and **system volume**, remap single/double/long presses, and use **Ctrl / Shift / Alt modifier layers** for contextual rotary actions.

## Current release line: v0.3

### Available now

- Linux backend using `evdev`.
- Virtual input injection through `/dev/uinput`.
- Automatic detection of the tested MEETION knob event interface.
- Exclusive grab of the physical rotary node while KNOBController is active.
- Base knob modes:
  - Vertical scroll.
  - System volume.
- Knob gestures:
  - Click.
  - Double click.
  - Long press.
- Button remapping:
  - Mute.
  - Enter.
  - Esc.
  - Tab.
  - Space.
  - Play/Pause.
  - No action.
- Modifier-aware rotation:
  - `Ctrl + Knob` -> Zoom by default.
  - `Shift + Knob` -> Horizontal scroll by default.
  - `Alt + Knob` -> Tab switching by default.
- Modifier layers can be changed to:
  - Inherit base mode.
  - Vertical scroll.
  - Horizontal scroll.
  - Volume.
  - Zoom.
  - Tabs.
- Non-destructive modifier monitoring from sibling MEETION evdev keyboard nodes.
- Persistent schema-v3 configuration in `/etc/knob-controller/config.json`.
- Local HTTP API at `127.0.0.1:8766`.
- Server-Sent Events stream for live knob, gesture and modifier activity.
- Native GTK client.
- Tauri v0.3 desktop shell with a hardware/audio-control-surface interface.
- Capability-driven UI: controls only show as live when the daemon really supports them.
- Python unit tests for the engine, backend and modifier layer logic.

## Default control model

```text
BASE
Knob left/right       -> Scroll or Volume
Click                 -> Mute
Double Click          -> No action
Long Press            -> No action

CTRL LAYER
Ctrl + Knob           -> Zoom out / in

SHIFT LAYER
Shift + Knob          -> Horizontal scroll

ALT LAYER
Alt + Knob            -> Previous / next tab
```

All three modifier layers are configurable from the desktop UI and through the local API.

## Architecture

```text
                         ┌────────────────────┐
                         │   Tauri Desktop    │
                         │      UI v0.3       │
                         └─────────┬──────────┘
                                   │ HTTP + SSE
                                   │
MEETION knob evdev ────────────────┼──────────────┐
                                   │              │
MEETION keyboard sibling evdev ────┘              │
        │                                          │
        │ Ctrl / Shift / Alt state                 │
        ▼                                          ▼
┌───────────────────┐                     ┌───────────────────┐
│   GestureEngine   │ ──────────────────> │   ActionEngine    │
└───────────────────┘                     └─────────┬─────────┘
                                                   │
                                                   ▼
                                         ┌───────────────────┐
                                         │ LinuxActionExecutor│
                                         └─────────┬─────────┘
                                                   │
                                      /dev/uinput  │
                                                   ▼
                                             Linux desktop
```

The portable core remains intentionally separate from Linux device code:

```text
physical rotary input
        ↓
device adapter / OS input backend
        ↓
gesture engine
        ↓
profile + modifier layer
        ↓
action engine
        ↓
OS execution backend
```

## Modifier-aware binding model

Profiles can now distinguish the same rotary gesture by its modifier context.

```text
rotate_right
ctrl+rotate_right
shift+rotate_right
alt+rotate_right
```

Resolution always checks the exact modifier binding first and then falls back to the plain gesture. That keeps old configurations usable when a specific layer has not been defined.

## Local API

The Tauri UI talks to:

```text
http://127.0.0.1:8766
```

Current endpoints:

```text
GET  /api/status
GET  /api/profiles
GET  /events

POST /api/mode
POST /api/click-map
POST /api/gesture-map
POST /api/modifier-map
```

Example modifier update:

```json
{
  "modifier": "shift",
  "mode": "horizontal_scroll"
}
```

The `/api/status` response exposes real runtime capabilities, detected modifier input nodes, active modifiers and the active mapping configuration. The desktop UI uses those values instead of assuming that a feature exists.

## Configuration schema v3

```json
{
  "schema_version": 3,
  "mode": "scroll",
  "click_key": "mute",
  "gesture_bindings": {
    "click": "mute",
    "double_click": "noop",
    "long_press": "noop"
  },
  "modifier_modes": {
    "ctrl": "zoom",
    "shift": "horizontal_scroll",
    "alt": "tabs"
  }
}
```

Older `click_key` configuration remains supported during migration.

## UI philosophy

The desktop interface is inspired by physical audio control surfaces rather than a generic settings dashboard.

The rules are strict:

1. **Real functions look active.**
2. **Unavailable functions stay disabled or explicitly marked NEXT.**
3. **No fake battery, firmware, haptics or telemetry.**
4. **Hardware activity must be visible immediately.**
5. **The UI is a control surface, not a configuration form.**

In v0.3 the UI shows live base mode, Click / Double Click / Long Press, modifier-node availability, currently held Ctrl/Shift/Alt keys and the action layer used by each modifier.

## Repository map

```text
.
├── knob_engine.py                      # portable gesture/action/profile engine
├── linux_backend.py                    # Linux action executor
├── modifier_input.py                   # Linux Ctrl/Shift/Alt state monitor
├── knob_controller_daemon.py           # current Linux daemon v0.3
├── knob-controller.py                  # legacy v0.x implementation
├── knob-controller-agent.py            # local agent
├── knob-controller.service             # systemd service definition
├── knob-controller-agent.service
├── test_linux_backend.py
├── test_modifier_layers.py
├── tests/
│   └── test_knob_engine.py
└── native-app/
    ├── knob-controller-native.py        # GTK client
    └── tauri/
        ├── ui/                          # legacy/fallback Tauri UI
        ├── ui-v2/index.html             # current hardware-control UI
        └── src-tauri/                   # Tauri application shell
```

## Platform direction

### Linux

Current production target.

```text
evdev + modifier nodes
        ↓
KNOBController engine
        ↓
uinput keyboard + pointer
```

### Windows

Planned native backend.

```text
Raw HID / Windows input APIs
        ↓
KNOBController engine
        ↓
SendInput
```

### macOS

Planned native backend.

```text
IOKit / HID
        ↓
KNOBController engine
        ↓
macOS input APIs
```

The Linux daemon cannot simply be repackaged unchanged for Microsoft Store or Mac App Store because `evdev` and `/dev/uinput` are Linux-specific. The portable gesture/action/profile engine is the part intended to be shared.

## Next product milestone: v0.4

The next major feature is **per-application profiles and automatic foreground-app switching**.

Target behavior:

```text
Browser
  Knob          -> Scroll
  Ctrl + Knob   -> Zoom
  Shift + Knob  -> Horizontal scroll
  Alt + Knob    -> Tabs

Spotify
  Knob          -> Volume
  Click         -> Play / Pause

Premiere / DaVinci
  Knob          -> Timeline scrub
  Shift + Knob  -> Fine scrub
  Ctrl + Knob   -> Timeline zoom

Photoshop / design tools
  Knob          -> Brush size
  Ctrl + Knob   -> Zoom
```

After profiles:

- generic HID discovery;
- multiple rotary devices;
- device adapters instead of a MEETION-only detector;
- packaged Linux installer;
- Windows backend;
- macOS backend;
- versioned GitHub Releases and signed installers.

## Public-release targets

Before `v1.0.0`, the project should have:

- generic device-adapter abstraction;
- supported-device matrix;
- packaged Linux installer;
- automated build artifacts;
- GitHub Releases;
- checksums;
- screenshots and demo video/GIF;
- `CHANGELOG.md`;
- `CONTRIBUTING.md`;
- `SECURITY.md`;
- issue templates;
- Windows/macOS backend milestones.

## License

KNOBController is open-source software from Edge Marketing Agency / EMA. See `LICENSE` for the repository license.

Project: **KNOBController**  
Product line: **Turn any keyboard knob into a control surface.**
