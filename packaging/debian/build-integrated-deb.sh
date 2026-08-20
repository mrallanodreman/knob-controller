#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <tauri-deb> [output-dir]" >&2
  exit 2
fi

TAURI_DEB="$(readlink -f "$1")"
OUT_DIR="${2:-dist}"
OUT_DIR="$(readlink -f "$OUT_DIR")"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$OUT_DIR"

# Arch/CachyOS no trae dpkg-deb; se extrae el .deb con ar+tar (formato ar y
# control/data en tar.gz). La estructura resultante es idéntica a dpkg-deb -R.
mkdir -p "$WORK/pkg"
(
  cd "$WORK/pkg"
  ar x "$TAURI_DEB"
  mkdir -p ctrl data
  tar xzf control.tar.gz -C ctrl
  tar xzf data.tar.gz -C data
  # control es DEBIAN/, data es la raíz /
  mv ctrl DEBIAN
  mv data/* .
  rm -f control.tar.gz data.tar.gz debian-binary
)
PKG="$WORK/pkg"

install -d -m 0755 \
  "$PKG/usr/lib/knob-controller" \
  "$PKG/usr/bin" \
  "$PKG/lib/systemd/system" \
  "$PKG/usr/lib/systemd/user" \
  "$PKG/lib/udev/rules.d" \
  "$PKG/etc/knob-controller"

cp -a "$ROOT_DIR/knob_controller" "$PKG/usr/lib/knob-controller/"
cp -a "$ROOT_DIR/devices" "$PKG/usr/lib/knob-controller/"
for file in knob_controller_daemon.py knob_engine.py linux_backend.py modifier_input.py app_context.py knob-controller-agent.py; do
  install -m 0644 "$ROOT_DIR/$file" "$PKG/usr/lib/knob-controller/$file"
done

cat > "$PKG/usr/bin/knob-controller" <<'EOF'
#!/usr/bin/env bash
export PYTHONPATH=/usr/lib/knob-controller${PYTHONPATH:+:$PYTHONPATH}
exec python3 -m knob_controller "$@"
EOF
chmod 0755 "$PKG/usr/bin/knob-controller"

cat > "$PKG/usr/bin/knob-controller-agent" <<'EOF'
#!/usr/bin/env bash
export PYTHONPATH=/usr/lib/knob-controller${PYTHONPATH:+:$PYTHONPATH}
exec python3 /usr/lib/knob-controller/knob-controller-agent.py "$@"
EOF
chmod 0755 "$PKG/usr/bin/knob-controller-agent"

install -m 0644 "$ROOT_DIR/packaging/systemd/knob-controller.service" "$PKG/lib/systemd/system/knob-controller.service"
install -m 0644 "$ROOT_DIR/packaging/systemd/knob-controller-agent.service" "$PKG/usr/lib/systemd/user/knob-controller-agent.service"
install -m 0644 "$ROOT_DIR/packaging/udev/70-knob-controller.rules" "$PKG/lib/udev/rules.d/70-knob-controller.rules"

python3 - "$PKG/DEBIAN/control" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
lines = p.read_text().splitlines()
need = ["python3", "x11-utils"]
for i, line in enumerate(lines):
    if line.startswith("Depends:"):
        current = [x.strip() for x in line.split(":",1)[1].split(",") if x.strip()]
        names = {x.split()[0] for x in current}
        current.extend(x for x in need if x not in names)
        lines[i] = "Depends: " + ", ".join(current)
        break
else:
    lines.append("Depends: " + ", ".join(need))
p.write_text("\n".join(lines) + "\n")
PY

cat > "$PKG/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
mkdir -p /etc/knob-controller
systemctl daemon-reload >/dev/null 2>&1 || true
systemctl enable knob-controller.service >/dev/null 2>&1 || true
systemctl restart knob-controller.service >/dev/null 2>&1 || true
udevadm control --reload-rules >/dev/null 2>&1 || true
exit 0
EOF
chmod 0755 "$PKG/DEBIAN/postinst"

cat > "$PKG/DEBIAN/prerm" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = remove ] || [ "$1" = deconfigure ]; then
  systemctl disable --now knob-controller.service >/dev/null 2>&1 || true
fi
exit 0
EOF
chmod 0755 "$PKG/DEBIAN/prerm"

cat > "$PKG/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e
systemctl daemon-reload >/dev/null 2>&1 || true
udevadm control --reload-rules >/dev/null 2>&1 || true
exit 0
EOF
chmod 0755 "$PKG/DEBIAN/postrm"

VERSION="$(PYTHONPATH="$ROOT_DIR" python3 -c 'import knob_controller; print(knob_controller.__version__)')"
# Architecture desde DEBIAN/control (antes dpkg-deb -f)
ARCH="$(grep -E '^Architecture:' "$PKG/DEBIAN/control" | awk '{print $2}')"
OUT="$OUT_DIR/knob-controller_${VERSION}_${ARCH}.deb"
# Construir .deb con ar+tar: debian-binary + control.tar.gz + data.tar.gz
mkdir -p "$WORK/build"
(
  cd "$WORK/build"
  echo "2.0" > debian-binary
  tar czf control.tar.gz --owner=0 --group=0 -C "$PKG" DEBIAN
  tar czf data.tar.gz --owner=0 --group=0 -C "$PKG" \
    --exclude=DEBIAN \
    usr lib etc 2>/dev/null
  ar rcs "$OUT" debian-binary control.tar.gz data.tar.gz
)
echo "$OUT"
