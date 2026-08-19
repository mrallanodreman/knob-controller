# Per-application profiles

KNOBController v0.5 includes an unprivileged desktop-session profile agent plus a visual editor.

The hardware daemon continues to own evdev/uinput. The profile agent runs as the logged-in desktop user, detects the foreground application, selects the first matching enabled profile, and applies its mapping through the daemon localhost API.

```text
Foreground app
    ↓
Profile Agent :8767
    ↓
Hardware Daemon :8766
    ↓
Gesture Engine → Action Engine → Linux backend → uinput
```

## Visual editor

The Tauri app now ships a dedicated **Profile Editor** window. Normal users no longer need to edit `profiles.json` by hand.

The editor can:

- create profiles;
- duplicate profiles;
- edit name and application/title match strings;
- enable or disable a profile;
- choose base Scroll or Volume behavior;
- configure Click, Double Click and Long Press;
- configure Ctrl, Shift and Alt rotary layers;
- use the currently focused app as a match rule;
- move profiles up/down to change matching priority;
- delete non-global profiles;
- show the current foreground app and active profile live.

The Global profile is protected from deletion so the system always has a safe fallback.

## Local profile API

Read/runtime endpoints:

```text
GET  http://127.0.0.1:8767/api/status
GET  http://127.0.0.1:8767/api/profiles
GET  http://127.0.0.1:8767/events
```

Editor endpoints:

```text
POST   /api/profiles
POST   /api/profiles/{id}
DELETE /api/profiles/{id}
POST   /api/profiles/reorder
POST   /api/profiles/use-current-app
```

All endpoints bind only to `127.0.0.1`.

## Persistent configuration

The agent stores profiles in:

```text
~/.config/knob-controller/profiles.json
```

v0.5 writes schema version 2. The file remains human-readable, but the visual editor is now the normal configuration path.

## Matching rules

`match` contains case-insensitive substrings tested against both the detected application id/class and the active window title. The first enabled matching profile wins. If nothing matches, `global` is used.

## Supported controls

Base mode:
- `scroll`
- `volume`

Button actions:
- `noop`
- `mute`
- `enter`
- `esc`
- `tab`
- `space`
- `playpause`

Modifier modes:
- `inherit`
- `scroll`
- `horizontal_scroll`
- `volume`
- `zoom`
- `tabs`

## Linux foreground-app support

Automatic foreground-app detection currently works on X11 through EWMH `_NET_ACTIVE_WINDOW` using `xprop`.

Wayland is detected explicitly but does not pretend to have universal foreground-app support. Until compositor-specific backends are added, Wayland safely falls back to Global.

## User service

`knob-controller-agent.service` is a **systemd user service**. The foreground-window detector belongs to the graphical user session; the privileged hardware daemon remains isolated from desktop context.
