# KNOBController Native

Native GTK desktop client for `knob-controller.service`.

The Linux app talks to the local daemon at `http://127.0.0.1:8766`, shows a native drawn knob, and switches the hardware knob between `scroll` and `volume` modes.

Store direction:

- Microsoft Store: package the UI shell as MSIX and replace the Linux daemon with a Windows HID backend.
- Mac App Store: package the UI shell as a signed/sandboxed macOS app and replace the Linux daemon with an IOKit/HID backend.
- The current Linux daemon uses `evdev` and `/dev/uinput`, which are Linux-specific and cannot ship unchanged to Microsoft Store or Mac App Store.
