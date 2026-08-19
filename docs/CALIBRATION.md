# Device calibration

KNOBController v0.8 can learn unknown Linux rotary devices from evdev events instead of requiring a handwritten adapter for every keyboard model.

## Supported learned layouts

Two runtime layouts are accepted:

```text
EV_KEY rotation
left  = key code A
right = key code B
press = key code C
```

or:

```text
EV_REL rotation
left  = axis code X, learned direction
right = axis code X, opposite direction
press = EV_KEY code C
```

Left and right may also use different relative-axis codes. Rotation events must be non-zero. Press must be `EV_KEY` so the gesture engine can observe press/release and preserve Click, Double Click and Long Press.

## Visual workflow

The Tauri app includes a dedicated **Device Calibration** window.

1. Rescan candidates.
2. Select an unknown candidate.
3. Start calibration.
4. Arm **TURN LEFT** and rotate exactly one detent.
5. Arm **TURN RIGHT** and rotate exactly one detent.
6. Arm **PRESS KNOB** and press once.
7. Confirm that Runtime Compatible shows **YES**.
8. Save the device profile.

Each step is armed manually. This is intentional: automatically arming the next step could learn rebound or residual events from the previous movement.

## Persistence

Calibrated devices are stored in:

```text
/etc/knob-controller/devices.json
```

The v0.8 store schema persists event `type`, `code`, and learned `value`/direction for each control.

Older v0.7 EV_KEY profiles remain compatible. Old diagnostic EV_REL profiles did not persist direction and therefore must be recalibrated rather than guessed.

## API

```text
GET  /api/devices
GET  /api/calibration
POST /api/calibration/start
POST /api/calibration/arm
POST /api/calibration/cancel
POST /api/calibration/save
GET  /events
```

Calibration state and captured events are also emitted over the existing SSE stream.

## Safety rules

- Generic/unknown candidates are never automatically grabbed for calibration.
- The currently active grabbed device cannot be calibrated simultaneously.
- `EV_SYN` and unsupported event types are ignored.
- Key releases/repeats are ignored while learning key-style rotation.
- A saved profile is only considered runtime-compatible when its learned map passes decoder validation.

## Runtime path

```text
physical knob
    ↓
evdev
    ↓
calibrated EventSpec
    ↓
RuntimeEventMap decoder
    ↓
GestureEngine
    ↓
ActionEngine
    ↓
LinuxActionExecutor
    ↓
uinput
```
