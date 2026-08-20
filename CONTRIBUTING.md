# Contributing to KNOBController

KNOBController is evolving toward a cross-platform rotary-input control layer. Contributions should preserve the separation between hardware discovery, normalized gestures/actions, desktop context, and OS backends.

## Development principles

1. Do not hard-code new hardware into the core daemon when it belongs in a device adapter or calibration fixture.
2. Do not run desktop-context detection as root.
3. Unknown devices must never be silently grabbed.
4. New UI capabilities must reflect real backend capabilities; do not add fake telemetry.
5. Keep Linux-specific event execution behind the Linux backend boundary.
6. Add hardware-free unit tests whenever a decoder, adapter, gesture, action or profile rule changes.

## Local checks

```bash
python3 -m py_compile \
  knob_controller/daemon.py \
  knob_controller/devices/service.py \
  knob_controller/calibration/service.py \
  devices/decoder.py

python3 -m unittest discover -v
```

For the Tauri UI:

```bash
cd native-app/tauri
npm install
npm run tauri build
```

## Pull requests

Keep PRs focused and describe:
- hardware/session tested;
- behavior before/after;
- safety implications;
- new API/config schema changes;
- tests added.

When adding support for new devices, include vendor/product IDs when known and document whether support is adapter-based or calibration-based.
