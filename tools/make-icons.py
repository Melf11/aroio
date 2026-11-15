#!/usr/bin/env python3
"""Render the PWA icons (PNG) from the logo geometry in web/public/icons/logo.svg.

    .venv/bin/python tools/make-icons.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "web" / "public" / "icons"
BRAND, INK = (0, 170, 170), (6, 38, 38)
# Home screen icons are dark in ABACUS colours (dark teal, bright teal bars, like the
# dark logo): iOS cannot be given its own dark variant of a web app icon and turns a
# light icon black and white in dark mode; a dark icon should keep its colours.
DARK, BRIGHT = (11, 46, 46), (0, 194, 194)
BARS = [(14, 38, 26), (22, 44, 20), (30, 40, 24), (38, 48, 16), (46, 40, 24), (54, 34, 30)]


def draw(size, radius=True, inset=0.0, ink=BRIGHT, bg=DARK):
    scale = 4
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if radius:
        d.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 16 / 64), fill=bg)
    else:
        d.rectangle([0, 0, s, s], fill=bg)
    k = s * (1 - 2 * inset) / 64
    off = s * inset
    w = 4.5 * k
    for x, y1, y2 in BARS:
        cx = off + x * k
        d.rounded_rectangle([cx - w / 2, off + y2 * k - w / 2, cx + w / 2, off + y1 * k + w / 2], radius=w / 2, fill=ink)
    return img.resize((size, size), Image.LANCZOS)


OUT.mkdir(parents=True, exist_ok=True)
draw(192).save(OUT / "icon-192.png")
draw(512).save(OUT / "icon-512.png")
draw(512, radius=False, inset=0.12).save(OUT / "icon-maskable-512.png")
draw(180, radius=False).save(OUT / "apple-touch-icon.png")   # iOS rounds itself
# the same at the conventional root paths: iOS, Android and browsers ask for these directly
ROOT = OUT.parent
draw(180, radius=False).save(ROOT / "apple-touch-icon.png")
draw(180, radius=False).save(ROOT / "apple-touch-icon-precomposed.png")
draw(64, ink=INK, bg=BRAND).save(ROOT / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
print("ok", sorted(p.name for p in OUT.glob("*.png")), sorted(p.name for p in ROOT.glob("*.png")) + ["favicon.ico"])
