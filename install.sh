#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "Run with sudo: sudo ./install.sh" >&2
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR=/usr/lib/knob-controller
BIN_DIR=/usr/bin
SYSTEMD_DIR=/etc/systemd/system
USER_SYSTEMD_DIR=/usr/lib/systemd/user
UDEV_DIR=/etc/udev/rules.d

command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }

install -d -m 0755 "$LIB_DIR" "$BIN_DIR" "$SYSTEMD_DIR" "$USER_SYSTEMD_DIR" "$UDEV_DIR"

rm -rf "$LIB_DIR/knob_controller" "$LIB_DIR/devices"
cp -a "$ROOT_DIR/knob_controller" "$LIB_DIR/"
cp -a "$ROOT_DIR/devices" "$LIB_DIR/"

for file in knob_controller_daemon.py knob_engine.py linux_backend.py modifier_input.py app_context.py knob-controller-agent.py; do
  install -m 0644 "$ROOT_DIR/$file" "$LIB_DIR/$file"
done

cat > "$BIN_DIR/knob-controller" <<'EOF'
#!/usr/bin/env bash
export PYTHONPATH=/usr/lib/knob-controller${PYTHONPATH:+:$PYTHONPATH}
exec python3 -m knob_controller "$@"
EOF
chmod 0755 "$BIN_DIR/knob-controller"

cat > "$BIN_DIR/knob-controller-agent" <<'EOF'
#!/usr/bin/env bash
export PYTHONPATH=/usr/lib/knob-controller${PYTHONPATH:+:$PYTHONPATH}
exec python3 /usr/lib/knob-controller/knob-controller-agent.py "$@"
EOF
chmod 0755 "$BIN_DIR/knob-controller-agent"

install -m 0644 "$ROOT_DIR/packaging/systemd/knob-controller.service" "$SYSTEMD_DIR/knob-controller.service"
install -m 0644 "$ROOT_DIR/packaging/systemd/knob-controller-agent.service" "$USER_SYSTEMD_DIR/knob-controller-agent.service"
install -m 0644 "$ROOT_DIR/packaging/udev/70-knob-controller.rules" "$UDEV_DIR/70-knob-controller.rules"

install -d -m 0755 /etc/knob-controller

action_user="${SUDO_USER:-}"

systemctl daemon-reload
systemctl enable --now knob-controller.service
udevadm control --reload-rules || true
udevadm trigger --subsystem-match=misc --action=change || true

if [[ -n "$action_user" && "$action_user" != root ]]; then
  uid="$(id -u "$action_user")"
  if command -v runuser >/dev/null && [[ -d "/run/user/$uid" ]]; then
    runuser -u "$action_user" -- env XDG_RUNTIME_DIR="/run/user/$uid" systemctl --user daemon-reload || true
    runuser -u "$action_user" -- env XDG_RUNTIME_DIR="/run/user/$uid" systemctl --user enable --now knob-controller-agent.service || true
  fi
fi

echo "KNOBController installed."
echo "Daemon: systemctl status knob-controller"
echo "API: http://127.0.0.1:8766/api/status"
