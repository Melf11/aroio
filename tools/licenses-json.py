#!/usr/bin/env python3
"""Buildroot `make show-info` JSON -> [{name, version, license, url}] for the app
(Settings > About > Open source licenses). Host packages are left out."""
import json
import sys

KNOWN_URLS = {
    "camilladsp": "https://github.com/HEnquist/camilladsp", "squeezelite": "https://github.com/ralph-irving/squeezelite",
    "shairport-sync": "https://github.com/mikebrady/shairport-sync",
    "linux": "https://github.com/raspberrypi/linux", "bluez5_utils": "https://www.bluez.org",
    "bluez-alsa": "https://github.com/arkq/bluez-alsa", "python3": "https://www.python.org", "systemd": "https://systemd.io",
}

info = json.load(open(sys.argv[1]))
out = []
for name, p in sorted(info.items()):
    if p.get("type") != "target" or name in ("aroiod", "aroio-web") or p.get("virtual"):
        continue
    lic = p.get("licenses") or "unbekannt"
    out.append({"name": name, "version": p.get("version", ""), "license": lic, "url": KNOWN_URLS.get(name)})
json.dump(out, sys.stdout, ensure_ascii=False, indent=0)
