# Device discovery and adapters

KNOBController v0.6 introduces a device-adapter layer so rotary hardware discovery is no longer a single MEETION-only assumption.

## Layout

```text
devices/
├── base.py
├── linux_input.py
├── meetion.py
├── generic_hid.py
└── registry.py
```

## Discovery policy

Known adapters are evaluated first. Unknown relative-input evdev nodes may be surfaced by the Generic HID adapter, but v0.6 does **not** auto-select low-confidence generic candidates.

The tested MEETION device remains the first supported adapter and therefore preserves current behavior.

## API

The v0.6 daemon entrypoint adds:

```text
GET /api/devices
```

The endpoint returns discovered candidates, the active event path, and the selection policy.

`GET /api/status` also includes a `device_discovery` section and reports the `device_discovery` capability.

## Adapter contract

Each adapter receives parsed Linux input-device data and emits `DeviceCandidate` objects containing:

- adapter id
- stable candidate id
- human-readable name
- event path
- vendor/product ids when available
- capability hints
- adapter metadata

## Generic HID safety

A REL-capable evdev node is only a candidate signal, not proof of a rotary knob. Generic candidates are therefore discoverable but opt-in until a stronger probing/calibration flow is implemented.

## Next

The next device milestone is interactive calibration: rotate left, rotate right, press the knob, and let KNOBController learn the event mapping before saving a custom adapter profile.
