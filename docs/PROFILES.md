# Per-application profiles

KNOBController v0.4 adds an unprivileged desktop-session profile agent.

The hardware daemon continues to run separately and owns evdev/uinput. The profile agent runs as the logged-in desktop user, detects the foreground application, and applies the matching control mapping through the daemon's localhost API.

## Runtime split

```text
Desktop session
  foreground app
      ↓
knob-controller-agent.py
      ↓  localhost HTTP
127.0.0.1:8766
      ↓
knob_controller_daemon.py
      ↓
Action Engine → Linux backend → uinput
```

The profile agent exposes read-only runtime status on:

```text
http://127.0.0.1:8767/api/status
http://127.0.0.1:8767/api/profiles
http://127.0.0.1:8767/events
```

## Linux support in v0.4

Automatic foreground-app detection is implemented for X11 using the EWMH `_NET_ACTIVE_WINDOW` hint through `xprop`.

Wayland is detected explicitly, but automatic foreground-app routing is not enabled there yet because compositors intentionally do not expose one universal cross-desktop active-window API. On Wayland the agent falls back to the Global profile instead of guessing.

## Profile configuration

The agent creates this file on first run:

```text
~/.config/knob-controller/profiles.json
```

Example:

```json
{
  "schema_version": 1,
  "profiles": [
    {
      "id": "global",
      "name": "Global",
      "match": [],
      "mode": "scroll",
      "gesture_bindings": {
        "click": "mute",
        "double_click": "noop",
        "long_press": "noop"
      },
      "modifier_modes": {
        "ctrl": "zoom",
        "shift": "horizontal_scroll",
        "alt": "tabs"
      },
      "enabled": true
    },
    {
      "id": "media",
      "name": "Media",
      "match": ["spotify", "vlc", "mpv"],
      "mode": "volume",
      "gesture_bindings": {
        "click": "playpause",
        "double_click": "mute",
        "long_press": "noop"
      },
      "modifier_modes": {
        "ctrl": "inherit",
        "shift": "inherit",
        "alt": "inherit"
      },
      "enabled": true
    }
  ]
}
```

## Matching rules

`match` is a list of case-insensitive substrings. KNOBController tests them against both the X11 `WM_CLASS` value and the active window title.

The first enabled matching profile wins. If nothing matches, `global` is used.

Keep match strings specific enough to avoid accidental collisions.

## Supported profile actions in v0.4

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

## Default profiles

The built-in first-run configuration includes:

- Global
- Browser
- Media
- Video Editor
- Design
- IDE

These are starter profiles, not hard-coded product restrictions. Users can edit the JSON file and restart the user agent.

## User service

The supplied `knob-controller-agent.service` is intended to be installed as a **systemd user service**, not a system-wide root service.

Typical installation target:

```text
~/.config/systemd/user/knob-controller-agent.service
```

Then:

```bash
systemctl --user daemon-reload
systemctl --user enable --now knob-controller-agent.service
```

This separation is intentional: the foreground-window detector belongs to the user's graphical session, while the hardware daemon remains isolated from it.
