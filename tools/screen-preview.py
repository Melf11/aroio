#!/usr/bin/env python3
"""Renders the HDMI info screen (aroiod/screen.py) for a few states into PNGs.

    .venv/bin/python tools/screen-preview.py [out-dir] [cover.jpg]

Needs Pillow and segno (.venv) and Inter in .dev/fonts (see font-inter package)."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PIL import Image  # noqa: E402

from aroiod.screen import Screen  # noqa: E402

out = Path(sys.argv[1] if len(sys.argv) > 1 else ".dev/screen")
out.mkdir(parents=True, exist_ok=True)
cover = Image.open(sys.argv[2]) if len(sys.argv) > 2 else None
now = time.mktime((2026, 11, 19, 20, 42, 0, 0, 0, -1))
base = {"name": "Wohnzimmer", "hostname": "aroio", "lan": "192.168.1.207", "now": now}
states = {
    "1-startet": {"starting": True},
    "2-einrichtung": {**base, "hotspot": "Aroio-Einrichtung-B515"},
    "3-bereit": {**base, "wifi": "192.168.1.208"},
    "4-spotify": {**base, "state": "playing", "source": "Spotify", "title": "Black Honey", "artist": "Thrice",
                  "album": "To Be Everywhere Is to Be Nowhere", "duration": 239.0, "position": 87.0,
                  "format": {"codec": "FLAC", "rate": 44100}, "volume": 42, "preset": "Raumkorrektur Wohnzimmer",
                  "cover": cover, "cover_id": "c1"},
    "5-lang-ohne-cover": {**base, "state": "paused", "source": "AirPlay",
                          "title": "Concerto for Piano and Orchestra No. 21 in C Major, K. 467: II. Andante",
                          "artist": "Wolfgang Amadeus Mozart, Wiener Philharmoniker, Mitsuko Uchida",
                          "album": "Mozart: Piano Concertos Nos. 20 & 21", "duration": 412.0, "position": 301.0,
                          "format": {"codec": "ALAC", "bits": 24, "rate": 96000}, "volume": 0, "muted": True},
}
menu = {"open": True, "title": "Aroio", "index": 2, "depth": 1, "rev": 3, "items": [
    {"label": "Pause"}, {"label": "Nächster Titel"}, {"label": "Lautstärke", "value": "42 %", "adjust": True},
    {"label": "Klang", "value": "Raumkorrektur Wohnzimmer", "open": "sound"}, {"label": "Favoriten", "open": "favorites"},
    {"label": "Schließen"}]}
sound = {"open": True, "title": "Klang", "index": 1, "depth": 2, "rev": 4, "items": [
    {"label": "Ohne Korrektur"}, {"label": "Raumkorrektur Wohnzimmer", "active": True}, {"label": "BBC-Dip"},
    {"label": "Echo"}, {"label": "Kopfhörer: Sennheiser HD 600"}, {"label": "Eigener Equalizer"},
    {"label": "Loudness"}, {"label": "Mono", "value": "aus"}]}
states["6-menue"] = {**states["4-spotify"], "menu": menu}
states["7-menue-klang"] = {**states["4-spotify"], "menu": sound}
states["8-lautstaerke"] = {**states["4-spotify"], "volume": 47, "menu": {"open": False, "volume_overlay": True}}
for name, st in states.items():
    sc = Screen()
    t = time.perf_counter()
    boxes = sc.draw(st)
    full = time.perf_counter() - t
    if name == "4-spotify":
        t = time.perf_counter()
        small = sc.draw({**st, "position": 88.0})
        print(f"  progress tick: {small} in {1000 * (time.perf_counter() - t):.1f} ms")
    sc.image.save(out / f"{name}.png")
    print(f"{name}: {len(boxes)} region(s), {1000 * full:.0f} ms")
