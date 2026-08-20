# Security Policy

KNOBController handles privileged Linux input devices and `/dev/uinput`, so security reports are treated as high priority.

## Supported versions

Security fixes target the latest release candidate and the latest stable release once v1.0 is published.

## Reporting a vulnerability

Please do not open a public issue for vulnerabilities that could allow privilege escalation, arbitrary input injection, unsafe device grabbing, local API abuse, or unintended access to keyboard/input events.

Use GitHub's private vulnerability reporting/security advisory flow for this repository when available. Include:

- affected version/commit;
- Linux distribution/session type;
- reproduction steps;
- expected vs actual behavior;
- whether root/systemd/udev involvement is required;
- suggested mitigation if known.

## Security boundaries

- The hardware daemon is privileged because Linux evdev access can expose sensitive input.
- The Profile Agent runs as the desktop user and should not access physical input devices.
- The daemon API binds to `127.0.0.1` only.
- Unknown generic input devices are never auto-grabbed.
- Packaging intentionally does not grant broad read access to `/dev/input/event*`.
