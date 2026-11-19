"""HDMI info screen on the device: python -m aroiod.hdmi (unit aroio-infoscreen).

Draws aroiod/screen.py into the framebuffer of the KMS driver (/dev/fb0) and copies only
what changed. Works only while a display is connected (DRM connector status): without
one it checks every 2 s and draws nothing. After 10 minutes without music the picture
is switched off (TVs go to standby, no burn-in); any change switches it on again.
"""

import fcntl
import glob
import io
import json
import logging
import mmap
import os
import sys
import time
import urllib.request

from PIL import Image

from .screen import H, W, Screen

log = logging.getLogger("aroiod.hdmi")

API = "http://127.0.0.1/api/v1/internal"
FB = "/dev/fb0"
SYS_FB = "/sys/class/graphics/fb0"
IDLE_BLANK = 600                    # s without music, then the picture goes off
BOOT_SECONDS = "/data/aroio/boot-seconds"   # uptime when aroiod answered last time: the progress bar

KDSETMODE, KD_TEXT, KD_GRAPHICS = 0x4B3A, 0x00, 0x01
FBIOBLANK, FB_BLANK_UNBLANK, FB_BLANK_POWERDOWN = 0x4611, 0, 4


def hdmi_connected():
    for path in glob.glob("/sys/class/drm/card*-HDMI-A-*/status"):
        try:
            if open(path).read().strip() == "connected":
                return True
        except OSError:
            continue
    return False


def get_json(path):
    try:
        with urllib.request.urlopen(API + path, timeout=2) as r:
            return json.load(r)
    except (OSError, ValueError):
        return None


def get_cover():
    try:
        with urllib.request.urlopen(API + "/cover", timeout=5) as r:
            img = Image.open(io.BytesIO(r.read()))
            img.draft("RGB", (600, 600))         # JPEG: decode at reduced size, much faster
            return img.convert("RGB")
    except (OSError, ValueError):
        return None


class Framebuffer:
    """/dev/fb0 of the KMS driver (fbdev emulation), 32 or 16 bit."""

    def __init__(self, path=FB, sysfs=SYS_FB):
        w, h = (int(v) for v in open(f"{sysfs}/virtual_size").read().split(","))
        self.size = (w, h)
        self.bpp = int(open(f"{sysfs}/bits_per_pixel").read())
        self.stride = int(open(f"{sysfs}/stride").read())
        self.fd = os.open(path, os.O_RDWR)
        self.mem = mmap.mmap(self.fd, self.stride * h)
        if self.bpp not in (16, 32):
            raise ValueError(f"{self.bpp} bit framebuffer")

    def blit(self, part, dest):
        """part (an image) to dest = (x0, y0) on the framebuffer."""
        x0, y0 = dest
        w, h = part.size
        data = part.tobytes("raw", "BGRX") if self.bpp == 32 else rgb565(part)
        row = w * self.bpp // 8
        off = y0 * self.stride + x0 * self.bpp // 8
        for y in range(h):
            self.mem[off:off + row] = data[y * row:(y + 1) * row]
            off += self.stride

    def blank(self, on):
        try:
            fcntl.ioctl(self.fd, FBIOBLANK, FB_BLANK_POWERDOWN if on else FB_BLANK_UNBLANK)
        except OSError:
            pass

    def close(self):
        self.mem.close()
        os.close(self.fd)


def rgb565(img):
    """16 bit framebuffer (the KMS default without "-32" in video=): Pillow cannot pack it."""
    import numpy as np
    a = np.asarray(img.convert("RGB"), dtype=np.uint16)
    v = ((a[..., 0] >> 3) << 11) | ((a[..., 1] >> 2) << 5) | (a[..., 2] >> 3)
    return v.astype("<u2").tobytes()


def to_output(img, box, size, rotate):
    """The changed part of the 1920x1080 picture for the framebuffer: turned by 180° and
    scaled to its size if needed. Returns (part, (x, y) on the framebuffer)."""
    part = img.crop(box)
    if rotate == 180:
        part = part.rotate(180)
        box = (W - box[2], H - box[3], W - box[0], H - box[1])
    if size == (W, H):
        return part, box[:2]
    sx, sy = size[0] / W, size[1] / H
    x0, y0 = int(box[0] * sx), int(box[1] * sy)
    x1, y1 = min(size[0], int(round(box[2] * sx))), min(size[1], int(round(box[3] * sy)))
    return part.resize((max(1, x1 - x0), max(1, y1 - y0)), Image.BILINEAR), (x0, y0)


def boot_progress(uptime, expected):
    """0..0.95 while starting, eased towards the time the last start took."""
    import math
    return 0.95 * (1 - math.exp(-2.2 * uptime / max(expected, 3.0)))


def read_uptime():
    try:
        return float(open("/proc/uptime").read().split()[0])
    except (OSError, ValueError):
        return 0.0


def shutdown_text():
    """Stopped by systemd: restart or power off?"""
    import subprocess
    try:
        jobs = subprocess.run(["systemctl", "list-jobs", "--no-legend"], capture_output=True, text=True,
                              timeout=2).stdout
    except (OSError, subprocess.SubprocessError):
        jobs = ""
    return "Aroio wird ausgeschaltet …" if "poweroff.target" in jobs or "halt.target" in jobs \
        else "Aroio startet neu …"


def console_graphics(on):
    """tty1 (our stdin) in graphics mode: the text console does not draw over us."""
    try:
        fcntl.ioctl(0, KDSETMODE, KD_GRAPHICS if on else KD_TEXT)
    except OSError:
        pass


def run():
    import signal
    screen, fb = None, None
    cover_id, cover = None, None
    expected = None                         # read once /data is there (the screen starts before it)

    def boot_seconds():
        nonlocal expected
        if expected is None:
            try:
                expected = float(open(BOOT_SECONDS).read())
            except (OSError, ValueError):
                return 10.0
        return expected
    booting = read_uptime() < 120           # started with the system: progress bar until aroiod answers

    def stopping(_sig, _frame):
        # the system goes down: say so and leave the picture until the reset
        if screen is not None and fb is not None:
            for box in screen.draw({"starting": shutdown_text()}):
                fb.blit(*to_output(screen.image, box, fb.size, getattr(screen, "rotate", 0)))
        os._exit(0)
    signal.signal(signal.SIGTERM, stopping)
    rev = None                      # of the TV menu: aroiod answers at once when it changes
    last_music, blanked = time.monotonic(), False
    console_graphics(True)
    try:
        while True:
            if not hdmi_connected() or not os.path.exists(FB):
                if fb:
                    fb.close()
                    fb, screen = None, None
                    log.info("display disconnected")
                time.sleep(2)
                continue
            if fb is None:
                try:
                    fb = Framebuffer()
                except (OSError, ValueError) as exc:
                    log.warning("framebuffer: %s", exc)
                    time.sleep(2)
                    continue
                screen, blanked = Screen(), False
                log.info("display connected: %dx%d, %d bit", *fb.size, fb.bpp)
            status = get_json("/status" + (f"?wait={rev}" if rev is not None else ""))
            if status is None:
                status, rev = {"starting": True}, None
                if booting:
                    status["progress"] = boot_progress(read_uptime(), boot_seconds())
                time.sleep(0.25)
            else:
                rev = (status.get("menu") or {}).get("rev")
                if booting:
                    booting = False
                    up = read_uptime()
                    if abs(up - boot_seconds()) > 0.5:
                        try:
                            with open(BOOT_SECONDS, "w") as fh:
                                fh.write(f"{up:.1f}\n")
                        except OSError:
                            pass
            if status.get("cover_id") != cover_id:
                cover_id = status.get("cover_id")
                cover = get_cover() if cover_id else None
            status.update(cover=cover, now=time.time())
            active = status.get("state") == "playing" or status.get("hotspot") or status.get("starting")
            if active:
                last_music = time.monotonic()
            idle_off = time.monotonic() - last_music > IDLE_BLANK
            if idle_off != blanked:
                fb.blank(idle_off)
                blanked = idle_off
                log.info("picture %s", "off (idle)" if idle_off else "on")
            if not blanked:
                rotate = status.get("rotate") or 0
                if rotate != getattr(screen, "rotate", rotate):
                    screen = Screen()                       # everything again, turned
                screen.rotate = rotate
                for box in screen.draw(status):
                    fb.blit(*to_output(screen.image, box, fb.size, rotate))
            else:
                time.sleep(1)
    finally:
        console_graphics(False)


def main():
    logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s %(message)s", stream=sys.stderr)
    run()


if __name__ == "__main__":
    main()
