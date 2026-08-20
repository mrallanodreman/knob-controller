# Linux installation

## Release-candidate validation

Before tagging a release candidate, validate the canonical runtime and packaging scripts from a Linux checkout:

```bash
chmod +x scripts/rc-validate.sh
./scripts/rc-validate.sh
```

For a full desktop build, including Tauri bundles:

```bash
./scripts/rc-validate.sh --full
```

The normal validation compiles the Python runtime, imports the canonical package, runs unit tests, and checks the packaging scripts. `--full` additionally requires Node/npm and Rust/Cargo and builds the desktop bundles.

## Recommended: integrated `.deb`

The release workflow produces one Debian package that contains:

- the Tauri desktop application;
- the canonical Python runtime;
- the hardware daemon;
- the per-application Profile Agent;
- systemd units;
- the conservative `/dev/uinput` udev rule.

Install it with:

```bash
sudo apt install ./knob-controller_0.10.0-rc.1_amd64.deb
```

The package enables and starts the hardware daemon. The desktop Profile Agent is a user service; enable it in the logged-in desktop session with:

```bash
systemctl --user enable --now knob-controller-agent.service
```

Verify the hardware daemon:

```bash
systemctl status knob-controller
curl http://127.0.0.1:8766/api/status
```

## Portable bundle

The release also produces `knob-controller-linux-x86_64.tar.gz` containing the AppImage plus the source installer/runtime files. The AppImage is portable UI; install the system runtime once with:

```bash
tar -xzf knob-controller-linux-x86_64.tar.gz
sudo ./install.sh
./KNOBController.AppImage
```

## Source install

From a repository checkout:

```bash
sudo ./install.sh
```

This installs the runtime under `/usr/lib/knob-controller`, commands under `/usr/bin`, the daemon unit under `/etc/systemd/system`, and the user agent unit under `/usr/lib/systemd/user`.

## Uninstall

For the source installer:

```bash
sudo ./uninstall.sh
```

For the Debian package:

```bash
sudo apt remove knob-controller
```

Calibration and profile configuration are preserved by default. Remove `/etc/knob-controller` and `~/.config/knob-controller` manually only when you want to erase those settings too.

## Security note

KNOBController intentionally does **not** make every `/dev/input/event*` device world-readable. The hardware daemon remains the privileged boundary, while the Profile Agent and desktop UI run as the user.
