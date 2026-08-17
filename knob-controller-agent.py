#!/usr/bin/env python3
import fcntl
import json
import os
import select
import signal
import struct
import time
from pathlib import Path

CONFIG_PATH = Path("/etc/knob-controller/config.json")
EV_SYN = 0
EV_KEY = 1
EV_REL = 2
SYN_REPORT = 0
KEY_VOLUMEDOWN = 114
KEY_VOLUMEUP = 115
REL_WHEEL = 8
BUS_USB = 0x03

IOC_NRBITS = 8
IOC_TYPEBITS = 8
IOC_SIZEBITS = 14
IOC_NRSHIFT = 0
IOC_TYPESHIFT = IOC_NRSHIFT + IOC_NRBITS
IOC_SIZESHIFT = IOC_TYPESHIFT + IOC_TYPEBITS
IOC_DIRSHIFT = IOC_SIZESHIFT + IOC_SIZEBITS
IOC_NONE = 0
IOC_WRITE = 1


def ioc(direction, type_, nr, size):
    return (
        (direction << IOC_DIRSHIFT)
        | (ord(type_) << IOC_TYPESHIFT)
        | (nr << IOC_NRSHIFT)
        | (size << IOC_SIZESHIFT)
    )


UI_DEV_CREATE = ioc(IOC_NONE, "U", 1, 0)
UI_DEV_DESTROY = ioc(IOC_NONE, "U", 2, 0)
UI_SET_EVBIT = ioc(IOC_WRITE, "U", 100, struct.calcsize("i"))
UI_SET_RELBIT = ioc(IOC_WRITE, "U", 102, struct.calcsize("i"))
EVIOCGRAB = ioc(IOC_WRITE, "E", 0x90, struct.calcsize("i"))
EVENT = "llHHi"
EVENT_SIZE = struct.calcsize(EVENT)
running = True


def stop(_signum, _frame):
    global running
    running = False


def mode():
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8")).get("mode", "scroll")
    except Exception:
        return "scroll"


def resolve_source():
    data = Path("/proc/bus/input/devices").read_text(encoding="utf-8")
    for block in data.strip().split("\n\n"):
        if 'Name="Evision MEETION Keyboard"' not in block:
            continue
        if "REL=1040" not in block:
            continue
        for line in block.splitlines():
            if line.startswith("H: Handlers="):
                for token in line.split():
                    if token.startswith("event"):
                        return "/dev/input/" + token
    raise RuntimeError("MEETION knob event device not found")


def write_event(fd, ev_type, code, value):
    sec = int(time.time())
    usec = int((time.time() - sec) * 1_000_000)
    os.write(fd, struct.pack(EVENT, sec, usec, ev_type, code, value))


def create_scroll_device():
    fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
    fcntl.ioctl(fd, UI_SET_EVBIT, EV_REL)
    fcntl.ioctl(fd, UI_SET_RELBIT, REL_WHEEL)
    user_dev = struct.pack("80sHHHHi" + "i" * 64 * 4, b"KNOBController scroll agent", BUS_USB, 0x320F, 0x5055, 1, 0, *([0] * 64 * 4))
    os.write(fd, user_dev)
    fcntl.ioctl(fd, UI_DEV_CREATE)
    return fd


def main():
    if mode() != "scroll":
        print("KNOBController agent not needed in volume mode", flush=True)
        return
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    source = None
    out = None
    try:
        source_path = resolve_source()
        source = os.open(source_path, os.O_RDONLY | os.O_NONBLOCK)
        out = create_scroll_device()
        fcntl.ioctl(source, EVIOCGRAB, 1)
        print(f"KNOBController scroll agent active: {source_path}", flush=True)
        while running:
            ready, _, _ = select.select([source], [], [], 0.5)
            if not ready:
                continue
            data = os.read(source, EVENT_SIZE * 64)
            for idx in range(0, len(data) // EVENT_SIZE * EVENT_SIZE, EVENT_SIZE):
                _sec, _usec, ev_type, code, value = struct.unpack(EVENT, data[idx : idx + EVENT_SIZE])
                if ev_type != EV_KEY or value != 1:
                    continue
                if code == KEY_VOLUMEUP:
                    delta = 1
                elif code == KEY_VOLUMEDOWN:
                    delta = -1
                else:
                    continue
                write_event(out, EV_REL, REL_WHEEL, delta)
                write_event(out, EV_SYN, SYN_REPORT, 0)
    finally:
        if source is not None:
            try:
                fcntl.ioctl(source, EVIOCGRAB, 0)
            except Exception:
                pass
            os.close(source)
        if out is not None:
            try:
                fcntl.ioctl(out, UI_DEV_DESTROY)
            except Exception:
                pass
            os.close(out)


if __name__ == "__main__":
    main()
