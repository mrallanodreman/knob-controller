# Changelog

All notable changes to KNOBController are documented here.

## 0.10.0-rc.1 — Release candidate

### Added
- Integrated Linux packaging flow combining the Tauri desktop UI and Python hardware runtime into one Debian package.
- Source `install.sh` and `uninstall.sh` for development/source installs.
- Packaged systemd daemon and systemd user Profile Agent units.
- Conservative udev rule for `/dev/uinput` without relaxing access to all evdev input devices.
- GitHub Release workflow for Debian and portable AppImage bundles.
- SHA-256 checksum generation.
- Release/security/contribution/supported-device documentation.

### Changed
- Canonical installed entrypoints are `/usr/bin/knob-controller` and `/usr/bin/knob-controller-agent`.
- Runtime/Tauri/Cargo version moved to `0.10.0-rc.1`.

### Existing capabilities included in this RC
- EV_KEY and EV_REL rotary decoding.
- Device discovery and interactive calibration.
- Click, double-click and long-press gestures.
- Ctrl/Shift/Alt modifier layers.
- X11 per-application profiles and visual Profile Editor.

### Known limitations
- Automatic foreground application switching on Wayland is not universal yet.
- Windows and macOS backends are not part of this Linux release candidate.
- GitHub Actions test jobs have intermittently failed before exposing runner steps/logs; release artifacts must not be called verified until a successful release workflow completes.
