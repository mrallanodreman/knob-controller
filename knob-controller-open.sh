#!/usr/bin/env bash
set -euo pipefail
sudo systemctl start knob-controller.service
xdg-open http://127.0.0.1:8766/ >/tmp/knob-controller-open.log 2>&1 &
