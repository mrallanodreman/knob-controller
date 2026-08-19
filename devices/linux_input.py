from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class LinuxInputBlock:
    name: str
    handlers: tuple[str, ...]
    event_paths: tuple[str, ...]
    bus: str = ""
    vendor: str = ""
    product: str = ""
    version: str = ""
    rel: str = ""
    key: str = ""
    raw: str = ""


def parse_input_devices(text: str) -> list[LinuxInputBlock]:
    blocks: list[LinuxInputBlock] = []
    for raw in (text or "").strip().split("\n\n"):
        if not raw.strip():
            continue
        name = ""
        handlers: tuple[str, ...] = ()
        bus = vendor = product = version = rel = key = ""
        for line in raw.splitlines():
            if line.startswith("N: Name="):
                m = re.search(r'Name="(.*)"', line)
                if m:
                    name = m.group(1)
            elif line.startswith("H: Handlers="):
                handlers = tuple(line.split("=", 1)[1].split())
            elif line.startswith("I: "):
                for token in line[3:].split():
                    if "=" not in token:
                        continue
                    k, v = token.split("=", 1)
                    if k == "Bus": bus = v
                    elif k == "Vendor": vendor = v
                    elif k == "Product": product = v
                    elif k == "Version": version = v
            elif line.startswith("B: REL="):
                rel = line.split("=", 1)[1].strip()
            elif line.startswith("B: KEY="):
                key = line.split("=", 1)[1].strip()
        event_paths = tuple(f"/dev/input/{h}" for h in handlers if h.startswith("event"))
        blocks.append(LinuxInputBlock(name, handlers, event_paths, bus, vendor, product, version, rel, key, raw))
    return blocks
