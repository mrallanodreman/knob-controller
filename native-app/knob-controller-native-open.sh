#!/usr/bin/env bash
set -euo pipefail
sudo systemctl stop knob-controller-agent.service 2>/dev/null || true
sudo systemctl start knob-controller.service
exec /usr/local/bin/knob-controller-native
