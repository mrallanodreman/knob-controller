# KNOBController architecture — v0.9

v0.9 establishes one canonical production runtime:

```text
/usr/local/bin/knob-controller
        ↓
knob_controller.daemon
```

The old `knob_controller_daemon_v06.py`, `v07.py` and `v08.py` files are migration artifacts only. They are not the systemd entrypoint and should not receive new product features.

## Privilege boundary

```text
User session
────────────
Tauri UI
Profile Agent (127.0.0.1:8767)

Privileged hardware service
───────────────────────────
knob_controller.daemon (127.0.0.1:8766)
    ↓
DeviceService
    ↓
RuntimeEventMap
    ↓
GestureEngine
    ↓
ActionEngine
    ↓
LinuxActionExecutor
    ↓
evdev + uinput
```

The user-session profile agent owns foreground-window context. The hardware daemon owns evdev/uinput. The Tauri UI talks only to localhost APIs.

## Package boundaries

### `knob_controller.daemon`

Composes the production service, API, SSE stream, device loop and graceful shutdown.

### `knob_controller.devices`

Owns discovery, preferred-device selection and conversion of a selected adapter into a normalized runtime event map.

The persistent adapter implementations remain in the existing root `devices/` package for the v0.9 compatibility cycle.

### `knob_controller.calibration`

Owns calibration session lifecycle: start, arm, capture, cancel and save. HTTP code no longer owns calibration state.

### `knob_controller.backends`

Defines the canonical import boundary for platform backends. Linux currently delegates to the proven `linux_backend.py` and `modifier_input.py` implementations. Windows and macOS can later add sibling modules without changing the daemon's product model.

### `knob_controller.profiles`

Reserved package boundary for moving the current unprivileged profile-agent implementation into the package after the v0.9 compatibility cycle.

## Compatibility policy

v0.9 deliberately avoids a risky all-at-once rewrite. Proven root implementation modules remain importable for one compatibility cycle, but only the `knob_controller/` package is considered the active runtime architecture.

A future cleanup may physically move `knob_engine.py`, `linux_backend.py`, `modifier_input.py`, `app_context.py` and the root `devices/` implementation into the package while preserving the public module boundaries established here.

## Release goal

v0.9 is the architecture gate before packaging work. v1.0 packaging should depend on:

- one executable name: `knob-controller`;
- one systemd hardware service;
- one canonical Python package;
- predictable config locations;
- no versioned daemon wrappers in the installation path;
- reproducible tests/builds and signed release artifacts.
