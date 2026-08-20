#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

FULL=0
if [[ "${1:-}" == "--full" ]]; then
  FULL=1
fi

log() { printf '\n==> %s\n' "$*"; }

log "Environment"
uname -a
python3 --version
command -v python3

log "Compile canonical Python runtime"
python3 -m py_compile \
  knob_engine.py \
  linux_backend.py \
  modifier_input.py \
  app_context.py \
  devices/base.py \
  devices/linux_input.py \
  devices/meetion.py \
  devices/generic_hid.py \
  devices/decoder.py \
  devices/custom.py \
  devices/calibration.py \
  devices/registry.py \
  knob_controller/__init__.py \
  knob_controller/__main__.py \
  knob_controller/backends/linux.py \
  knob_controller/devices/service.py \
  knob_controller/calibration/service.py \
  knob_controller/daemon.py \
  knob_controller_daemon.py \
  knob-controller-agent.py

log "Import canonical runtime"
python3 - <<'PY'
import knob_controller
import knob_controller.daemon
print("KNOBController", knob_controller.__version__)
PY

log "Run unit tests"
python3 -m unittest discover -v

log "Validate packaging scripts"
bash -n install.sh uninstall.sh packaging/debian/build-integrated-deb.sh
grep -q '/usr/bin/knob-controller' packaging/systemd/knob-controller.service
grep -q 'uinput' packaging/udev/70-knob-controller.rules

echo "Packaging scripts: OK"

if [[ "$FULL" -eq 1 ]]; then
  log "Full desktop build"
  command -v npm >/dev/null || { echo "npm is required for --full" >&2; exit 1; }
  command -v cargo >/dev/null || { echo "cargo is required for --full" >&2; exit 1; }
  (
    cd native-app/tauri
    npm ci
    npm run tauri build
  )

  log "Locate release bundles"
  find native-app/tauri/src-tauri/target/release/bundle -maxdepth 3 -type f -print | sort
fi

log "RC validation complete"
echo "PASS"
