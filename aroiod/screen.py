"""The info screen on the HDMI output, drawn with Pillow (no browser, no GPU).

Screen.draw(status) brings self.image up to date and returns the boxes that changed, so
the device only copies those to the framebuffer (usually the progress bar once a second,
the whole picture only when the track or the state changes). Dark, ABACUS turquoise, Inter.

status is what /api/v1/internal/status returns (aroiod/web.py), plus "cover" (an RGB
image of the current cover, fetched by the caller) and "now" (time.time()).
"""

import time

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1920, 1080
M = 96                                     # outer margin

BG = (10, 17, 18)                          # app dark theme --bg
SURFACE = (24, 36, 37)                     # --surface-2
TRACK = (33, 48, 49)                       # --surface-3
TEXT = (231, 239, 239)                     # --text
TEXT_2 = (168, 186, 186)
TEXT_3 = (118, 140, 140)
BRAND = (0, 170, 170)                      # #00AAAA
BRAND_BRIGHT = (0, 194, 194)               # logo bars on dark
ON_BRAND = (6, 38, 38)
LOGO_BG = (11, 46, 46)

FONT_DIRS = ["/usr/share/fonts/inter", ".dev/fonts"]
WEIGHTS = {"regular": "Inter-Regular.ttf", "semibold": "Inter-SemiBold.ttf", "bold": "Inter-Bold.ttf"}
SS = 4                                     # supersampling for shapes (Pillow does not antialias them)


class Fonts:
    def __init__(self, dirs=FONT_DIRS):
        self.dirs, self.cache = dirs, {}

    def __call__(self, weight, size):
        key = (weight, size)
        if key not in self.cache:
            for d in self.dirs:
                try:
                    self.cache[key] = ImageFont.truetype(f"{d}/{WEIGHTS[weight]}", size)
                    break
                except OSError:
                    continue
            else:
                self.cache[key] = ImageFont.load_default(size)
        return self.cache[key]


# ── drawing helpers ──────────────────────────────────────────────────────────

def rrect(img, box, radius, fill):
    """Antialiased rounded rectangle (drawn SS times larger, scaled down)."""
    x0, y0, x1, y1 = [int(round(v)) for v in box]
    w, h = max(1, x1 - x0), max(1, y1 - y0)
    mask = Image.new("L", (w * SS, h * SS), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w * SS - 1, h * SS - 1), radius * SS, fill=255)
    mask = mask.resize((w, h), Image.LANCZOS)
    img.paste(Image.new("RGB", (w, h), fill), (x0, y0), mask)


def logo(img, x, y, size, background=True):
    """The app logo (web/public/icons/logo.svg, dark variant): six rounded bars."""
    s = size / 64
    layer = Image.new("L", (size * SS, size * SS), 0)
    d = ImageDraw.Draw(layer)
    sw = 4.5 * s * SS
    for bx, y1, y2 in ((14, 26, 38), (22, 20, 44), (30, 24, 40), (38, 16, 48), (46, 24, 40), (54, 30, 34)):
        cx = bx * s * SS
        d.rounded_rectangle((cx - sw / 2, y1 * s * SS - sw / 2, cx + sw / 2, y2 * s * SS + sw / 2), sw / 2, fill=255)
    bars = layer.resize((size, size), Image.LANCZOS)
    if background:
        rrect(img, (x, y, x + size, y + size), 16 * s, LOGO_BG)
    img.paste(Image.new("RGB", (size, size), BRAND_BRIGHT), (x, y), bars)


def fit(draw, text, font, width):
    """text shortened with … to width."""
    text = (text or "").strip()
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + "…", font=font) > width:
        text = text[:-1]
    return text.rstrip() + "…"


def wrap(draw, text, font, width, lines=2):
    """Up to `lines` lines, the last one shortened with …"""
    words, out, cur = (text or "").split(), [], ""
    for i, w in enumerate(words):
        cand = (cur + " " + w).strip()
        if draw.textlength(cand, font=font) <= width or not cur:
            cur = cand
            continue
        out.append(cur)
        cur = w
        if len(out) == lines - 1:
            cur = " ".join(words[i:])
            break
    if cur:
        out.append(fit(draw, cur, font, width))
    return out[:lines]


def clock_text(now):
    return time.strftime("%H:%M", time.localtime(now))


def mmss(seconds):
    seconds = max(0, int(seconds or 0))
    return f"{seconds // 60}:{seconds % 60:02d}"


def khz(rate):
    if not rate:
        return ""
    v = rate / 1000
    return (f"{v:.1f}".replace(".", ",").replace(",0", "") if v % 1 else f"{int(v)}") + " kHz"


def format_line(fmt):
    """{"codec": "FLAC", "bits": 24, "rate": 96000} -> "FLAC · 24 Bit · 96 kHz"."""
    fmt = fmt or {}
    parts = [fmt.get("codec")]
    if fmt.get("kbps"):
        parts.append(f"{fmt['kbps']} kbit/s")
    elif fmt.get("bits"):
        parts.append(f"{fmt['bits']} Bit")
    parts.append(khz(fmt.get("rate")))
    return " · ".join(p for p in parts if p)


def qr(img, x, y, size, data, dark=BG, light=TEXT):
    """QR code on a light rounded card (dark modules: every phone camera reads it)."""
    import segno
    code = segno.make(data, error="m")
    matrix = [list(row) for row in code.matrix]
    n = len(matrix)
    pad = size * 0.08
    cell = (size - 2 * pad) / n
    rrect(img, (x, y, x + size, y + size), size * 0.06, light)
    d = ImageDraw.Draw(img)
    for r, row in enumerate(matrix):
        for c, bit in enumerate(row):
            if bit:
                x0, y0 = x + pad + c * cell, y + pad + r * cell
                d.rectangle((round(x0), round(y0), round(x0 + cell) - 1, round(y0 + cell) - 1), fill=dark)


# ── the screen ───────────────────────────────────────────────────────────────

class Screen:
    """Keeps the current picture; draw() updates it and says which parts changed."""

    def __init__(self, size=(W, H), fonts=None):
        self.size = size
        self.font = fonts or Fonts()
        self.image = Image.new("RGB", size, BG)
        self._scene = None          # what the static part shows; redrawn when it changes
        self._dynamic = {}          # box -> last content of the parts that change by themselves
        self._backdrop_key = None
        self._backdrop = None

    # the parts that change without a new scene: clock, progress bar
    def draw(self, s):
        s = s or {}
        now = s.get("now") or time.time()
        scene = self._scene_key(s)
        changed = []
        if scene != self._scene:
            self._scene = scene
            self._dynamic = {}
            self._draw_scene(s)
            changed.append((0, 0) + self.size)
        for box, content, painter in self._dynamic_parts(s, now):
            if self._dynamic.get(box) != content:
                self._dynamic[box] = content
                painter()
                changed.append(box)
        return changed

    def _kind(self, s):
        if s.get("starting"):
            return "starting"
        if s.get("hotspot"):
            return "setup"
        if s.get("state") in ("playing", "paused") and s.get("title"):
            return "playing"
        return "idle"

    def _scene_key(self, s):
        kind = self._kind(s)
        keys = {"starting": (), "setup": ("hotspot",),
                "idle": ("name", "hostname", "lan", "wifi"),
                "playing": ("name", "source", "title", "artist", "album", "state", "preset",
                            "volume", "muted", "fixed_level", "cover_id")}[kind]
        fmt = format_line(s.get("format")) if kind == "playing" else ""
        return (kind, fmt) + tuple(str(s.get(k)) for k in keys)

    # ── static parts ──
    def _draw_scene(self, s):
        kind = self._kind(s)
        img = self.image
        img.paste(BG, (0, 0) + self.size)
        if kind == "playing":
            self._backdrop_paste(s)
        getattr(self, "_scene_" + kind)(s)

    def _backdrop_paste(self, s):
        """The cover, blurred and darkened, as the background (once per track, small)."""
        cover = s.get("cover")
        key = s.get("cover_id")
        if cover is None:
            self._backdrop_key = None
            return
        if key != self._backdrop_key:
            small = cover.convert("RGB").resize((48, 27), Image.BILINEAR).filter(ImageFilter.GaussianBlur(4))
            back = small.resize(self.size, Image.BILINEAR)
            self._backdrop = Image.blend(Image.new("RGB", self.size, BG), back, 0.28)
            self._backdrop_key = key
        self.image.paste(self._backdrop, (0, 0))

    def _header(self, s, show_name=True):
        img, d = self.image, ImageDraw.Draw(self.image)
        logo(img, M, 56, 56)
        if show_name:
            d.text((M + 56 + 22, 56 + 28), fit(d, s.get("name") or "Aroio", self.font("semibold", 32), 900),
                   font=self.font("semibold", 32), fill=TEXT_2, anchor="lm")

    def _scene_starting(self, s):
        img, d = self.image, ImageDraw.Draw(self.image)
        logo(img, W // 2 - 90, H // 2 - 150, 180)
        d.text((W // 2, H // 2 + 110), "Aroio startet …", font=self.font("semibold", 48), fill=TEXT_2, anchor="mm")

    def _scene_idle(self, s):
        img, d = self.image, ImageDraw.Draw(self.image)
        self._header(s, show_name=False)
        cx = 560
        logo(img, cx - 80, 300, 160)
        d.text((cx, 540), fit(d, s.get("name") or "Aroio", self.font("bold", 84), 900), font=self.font("bold", 84),
               fill=TEXT, anchor="mm")
        d.text((cx, 630), "Bereit", font=self.font("regular", 40), fill=TEXT_3, anchor="mm")
        # right: open the app
        host = s.get("hostname") or "aroio"
        url = f"http://{host}.local"
        x0 = 1080
        rrect(img, (x0, 250, W - M, 830), 32, SURFACE)
        d.text((x0 + 56, 310), "Zur App", font=self.font("semibold", 40), fill=TEXT, anchor="lm")
        d.text((x0 + 56, 372), "Code scannen oder im Browser öffnen:", font=self.font("regular", 30), fill=TEXT_2, anchor="lm")
        qr(img, x0 + 56, 430, 340, url)
        tx = x0 + 56 + 340 + 44
        d.text((tx, 470), fit(d, f"{host}.local", self.font("semibold", 36), W - M - tx - 40),
               font=self.font("semibold", 36), fill=BRAND_BRIGHT, anchor="lm")
        y = 540
        for label, kind in (("LAN", "lan"), ("WLAN", "wifi")):
            if s.get(kind):
                d.text((tx, y), label, font=self.font("regular", 28), fill=TEXT_3, anchor="lm")
                d.text((tx, y + 38), s[kind], font=self.font("semibold", 32), fill=TEXT_2, anchor="lm")
                y += 96

    def _scene_setup(self, s):
        img, d = self.image, ImageDraw.Draw(self.image)
        self._header(s, show_name=False)
        d.text((M, 250), "Aroio einrichten", font=self.font("bold", 84), fill=TEXT, anchor="lm")
        d.text((M, 330), "Zwei Schritte mit dem Handy", font=self.font("regular", 40), fill=TEXT_3, anchor="lm")
        ssid = s.get("hotspot") or "Aroio-Einrichtung"
        steps = [
            ("1", "Mit dem WLAN verbinden", ssid, f"WIFI:T:nopass;S:{ssid};;"),
            ("2", "Einrichtung öffnen", "http://192.168.4.1", "http://192.168.4.1"),
        ]
        for i, (num, title, value, data) in enumerate(steps):
            x0 = M + i * 880
            rrect(img, (x0, 420, x0 + 840, 940), 32, SURFACE)
            rrect(img, (x0 + 48, 468, x0 + 48 + 64, 468 + 64), 32, BRAND)
            d.text((x0 + 80, 500), num, font=self.font("bold", 36), fill=ON_BRAND, anchor="mm")
            d.text((x0 + 140, 500), title, font=self.font("semibold", 40), fill=TEXT, anchor="lm")
            d.text((x0 + 48, 590), fit(d, value, self.font("semibold", 36), 760), font=self.font("semibold", 36),
                   fill=BRAND_BRIGHT, anchor="lm")
            qr(img, x0 + 48, 640, 260, data)
            hint = "Code scannen oder in den WLAN-Einstellungen wählen" if i == 0 else \
                "Öffnet sich meist von selbst, sonst die Adresse eingeben"
            lines = wrap(d, hint, self.font("regular", 28), 440, lines=3)
            for j, line in enumerate(lines):
                d.text((x0 + 340, 680 + j * 40), line, font=self.font("regular", 28), fill=TEXT_2, anchor="lm")

    def _scene_playing(self, s):
        img, d = self.image, ImageDraw.Draw(self.image)
        self._header(s)
        size = 600
        cx, cy = M, (H - size) // 2 + 30
        # shadow, then the cover with rounded corners
        shadow = Image.new("L", (size + 160, size + 160), 0)
        ImageDraw.Draw(shadow).rounded_rectangle((80, 96, size + 80, size + 96), 28, fill=150)
        shadow = shadow.filter(ImageFilter.GaussianBlur(36))
        img.paste((0, 0, 0), (cx - 80, cy - 80), shadow)
        cover = s.get("cover")
        if cover is not None:
            c = cover.convert("RGB").resize((size, size), Image.LANCZOS)
        else:
            c = Image.new("RGB", (size, size), SURFACE)
            logo(c, size // 2 - 110, size // 2 - 110, 220, background=False)
        mask = Image.new("L", (size * 2, size * 2), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, size * 2 - 1, size * 2 - 1), 56, fill=255)
        img.paste(c, (cx, cy), mask.resize((size, size), Image.LANCZOS))

        tx, tw = cx + size + 96, W - (cx + size + 96) - M
        y = cy + 20
        source = s.get("source") or ""
        if source:
            f = self.font("semibold", 28)
            w = int(d.textlength(source, font=f)) + 48
            rrect(img, (tx, y, tx + w, y + 52), 26, BRAND)
            d.text((tx + w // 2, y + 26), source, font=f, fill=ON_BRAND, anchor="mm")
            if s.get("state") == "paused":
                d.text((tx + w + 24, y + 26), "Pause", font=self.font("semibold", 28), fill=TEXT_3, anchor="lm")
        y += 96
        title_font = self.font("bold", 76)
        for line in wrap(d, s.get("title"), title_font, tw, lines=2):
            d.text((tx, y), line, font=title_font, fill=TEXT, anchor="la")
            y += 92
        y += 12
        if s.get("artist"):
            d.text((tx, y), fit(d, s["artist"], self.font("semibold", 46), tw), font=self.font("semibold", 46),
                   fill=TEXT_2, anchor="la")
            y += 64
        if s.get("album"):
            d.text((tx, y), fit(d, s["album"], self.font("regular", 36), tw), font=self.font("regular", 36),
                   fill=TEXT_3, anchor="la")
        # bottom row under the progress bar: format, sound preset, volume
        by = cy + size - 30
        parts = [format_line(s.get("format")), ("Klang: " + s["preset"]) if s.get("preset") else ""]
        info = "   ·   ".join(p for p in parts if p)
        d.text((tx, by), fit(d, info, self.font("regular", 30), tw - 300), font=self.font("regular", 30),
               fill=TEXT_3, anchor="ls")
        if not s.get("fixed_level") and s.get("volume") is not None:
            vol = "Stumm" if s.get("muted") else f"{s['volume']} %"
            vx = tx + tw
            d.text((vx, by), vol, font=self.font("semibold", 30), fill=TEXT_2, anchor="rs")
            vw = int(d.textlength(vol, font=self.font("semibold", 30)))
            bar_w, bx = 160, vx - vw - 24 - 160
            rrect(img, (bx, by - 19, bx + bar_w, by - 11), 4, TRACK)
            if not s.get("muted") and s["volume"]:
                rrect(img, (bx, by - 19, bx + max(8, bar_w * s["volume"] / 100), by - 11), 4, BRAND_BRIGHT)
        self._layout = {"tx": tx, "tw": tw, "progress_y": cy + size - 120}

    # ── parts that change by themselves ──
    def _dynamic_parts(self, s, now):
        kind = self._kind(s)
        parts = []
        if kind != "starting":
            box = (W - M - 200, 52, W - M, 116)
            text = clock_text(now)
            parts.append((box, text, lambda b=box, t=text: self._paint_clock(b, t)))
        if kind == "playing" and s.get("duration"):
            lay = self._layout
            box = (lay["tx"], lay["progress_y"] - 10, lay["tx"] + lay["tw"], lay["progress_y"] + 52)
            pos = min(s.get("position") or 0, s["duration"])
            content = (int(pos), int(s["duration"]))
            parts.append((box, content, lambda b=box, p=pos, dur=s["duration"]: self._paint_progress(b, p, dur)))
        return parts

    def _restore(self, box):
        """Background under a part (backdrop or plain) before painting it again."""
        if self._kind_bg_is_backdrop():
            self.image.paste(self._backdrop.crop(box), box[:2])
        else:
            self.image.paste(BG, box)

    def _kind_bg_is_backdrop(self):
        return self._scene and self._scene[0] == "playing" and self._backdrop is not None and \
            self._backdrop_key is not None

    def _paint_clock(self, box, text):
        self._restore(box)
        ImageDraw.Draw(self.image).text((box[2], (box[1] + box[3]) // 2), text, font=self.font("semibold", 36),
                                        fill=TEXT_2, anchor="rm")

    def _paint_progress(self, box, pos, dur):
        self._restore(box)
        x0, y, x1 = box[0], box[1] + 10, box[2]
        rrect(self.image, (x0, y, x1, y + 8), 4, TRACK)
        if dur:
            rrect(self.image, (x0, y, x0 + max(8, (x1 - x0) * pos / dur), y + 8), 4, BRAND_BRIGHT)
        d = ImageDraw.Draw(self.image)
        f = self.font("regular", 28)
        d.text((x0, y + 26), mmss(pos), font=f, fill=TEXT_3, anchor="lt")
        d.text((x1, y + 26), mmss(dur), font=f, fill=TEXT_3, anchor="rt")
