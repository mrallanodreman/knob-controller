#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "Run with sudo: sudo ./uninstall.sh" >&2
  exit 1
fi

systemctl disable --now knob-controller.service 2>/dev/null || true
rm -f /etc/systemd/system/knob-controller.service
rm -f /usr/lib/systemd/user/knob-controller-agent.service
rm -f /etc/udev/rules.d/70-knob-controller.rules
rm -f /usr/bin/knob-controller /usr/bin/knob-controller-agent
rm -rf /usr/lib/knob-controller

systemctl daemon-reload
udevadm control --reload-rules 2>/dev/null || true

echo "KNOBController binaries and services removed."
echo "Configuration in /etc/knob-controller and ~/.config/knob-controller was preserved."
echo "Remove those directories manually only if you also want to delete calibrated devices and profiles."
