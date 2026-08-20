# Supported Devices

Support levels describe what KNOBController can safely claim in the current Linux release candidate.

| Device / family | Discovery | Rotation | Press | Calibration | Status |
| --- | --- | --- | --- | --- | --- |
| Evision / MEETION keyboard rotary interface used during development | Automatic adapter | EV_KEY | EV_KEY | Not required | Confirmed development hardware |
| Unknown Linux rotary device exposing REL-capable evdev node | Candidate only | EV_REL or EV_KEY after calibration | EV_KEY required | Visual calibration | Supported when calibration validates |
| Generic keyboard/mouse/touchpad with REL capability but no calibrated rotary mapping | Candidate only | Not auto-enabled | Not assumed | Manual only | Not supported as a knob until calibrated |
| Windows HID rotary devices | — | — | — | — | Planned |
| macOS HID rotary devices | — | — | — | — | Planned |

## Decoder layouts supported on Linux

```text
EV_KEY left + EV_KEY right + EV_KEY press
EV_REL left/right axis + EV_KEY press
```

For `EV_REL`, calibration stores the event code and direction/sign so larger accelerated values are interpreted in the learned direction.

## What “calibrated” means

A device is promoted from a generic candidate to a calibrated adapter only after the user explicitly records:

1. one left movement;
2. one right movement;
3. one knob press;
4. a runtime-compatible event map.

Unknown devices are never silently selected or grabbed.

## Reporting a device

When reporting working or non-working hardware, include:
- manufacturer and model;
- USB vendor/product IDs if available;
- Linux distribution;
- X11 or Wayland;
- whether rotation is EV_KEY or EV_REL;
- calibration result or relevant `/api/devices` output.
