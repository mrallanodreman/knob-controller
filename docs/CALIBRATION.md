# Interactive calibration

KNOBController v0.7 can learn unknown rotary devices that appear in the v0.6 discovery list.

## Flow

1. `GET /api/devices` and choose an unknown candidate.
2. `POST /api/calibration/start` with `device_id`.
3. Arm `left`, turn the knob left once.
4. Arm `right`, turn the knob right once.
5. Arm `press`, press the knob once.
6. Review `GET /api/calibration`.
7. `POST /api/calibration/save` with an optional display name.

Example start payload:

```json
{"device_id":"generic-hid:event9"}
```

Example arm payload:

```json
{"step":"left"}
```

Example save payload:

```json
{"name":"Studio keyboard knob"}
```

Saved device profiles live in:

```text
/etc/knob-controller/devices.json
```

They are loaded by the `calibrated` adapter during normal discovery.

## Safety and current decoder

v0.7 records the raw Linux input event type/code/value for all three steps, but automatic runtime activation is intentionally limited to devices whose left, right and press signals are `EV_KEY` events. This matches the proven MEETION event pattern and allows the existing gesture/action runtime to be reused safely.

Pure `EV_REL` rotary-axis devices can be observed during calibration, but the profile is marked unsupported by the v0.7 runtime decoder and cannot be saved as live until the REL decoder is added.

The active device cannot be calibrated while the hardware daemon has it exclusively grabbed. Calibration is intended for unknown candidates that are not currently selected.
