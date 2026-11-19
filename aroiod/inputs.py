"""Controls on the device via Linux input events (no lirc, no extra library).

    IR receiver (gpio-ir + rc-core)   EV_MSC/MSC_SCAN scancode -> Device.on_ir()
    rotary encoder (rotary-encoder)    EV_REL steps             -> Device.on_encoder()
    keys (gpio-keys, USB remotes)      EV_KEY press/repeat      -> Device.on_key()

The overlays come from models.boot_lines(); rc-core decodes all protocols
(aroio-ir.service runs `ir-keytable -p all`), the mapping scancode -> function
is hardware.ir_map (taught in the app).
"""

import asyncio
import logging
import os
import re
import struct
from pathlib import Path

log = logging.getLogger("aroiod.inputs")

EVENT = struct.Struct("llHHi")      # struct input_event on 64-bit: timeval, type, code, value
EV_KEY, EV_REL, EV_MSC = 1, 2, 4
MSC_SCAN = 4
KEYS = {113: "KEY_MUTE", 114: "KEY_VOLUMEDOWN", 115: "KEY_VOLUMEUP", 163: "KEY_NEXT", 164: "KEY_PLAYPAUSE",
        165: "KEY_PREVIOUS", 166: "KEY_STOP", 200: "KEY_PLAY", 201: "KEY_PAUSE",
        2: "KEY_1", 3: "KEY_2", 4: "KEY_3", 5: "KEY_4", 6: "KEY_5"}
REPEATING = {"KEY_VOLUMEUP", "KEY_VOLUMEDOWN"}
# TV remote over HDMI-CEC: the kernel's rc-cec keymap, input devices "vc4-hdmi-N"
CEC_KEYS = {28: "KEY_ENTER", 103: "KEY_UP", 108: "KEY_DOWN", 105: "KEY_LEFT", 106: "KEY_RIGHT",
            352: "KEY_OK", 353: "KEY_SELECT", 139: "KEY_MENU", 618: "KEY_ROOT_MENU", 141: "KEY_SETUP",
            174: "KEY_EXIT", 158: "KEY_BACK", 1: "KEY_ESC",
            200: "KEY_PLAY", 207: "KEY_PLAY", 201: "KEY_PAUSE", 119: "KEY_PAUSE", 164: "KEY_PLAYPAUSE",
            166: "KEY_STOP", 128: "KEY_STOP", 163: "KEY_NEXT", 208: "KEY_NEXT", 165: "KEY_PREVIOUS",
            168: "KEY_PREVIOUS", 113: "KEY_MUTE", 114: "KEY_VOLUMEDOWN", 115: "KEY_VOLUMEUP",
            **{0x201 + i: f"KEY_{i + 1}" for i in range(9)}}
CEC_REPEATING = {"KEY_UP", "KEY_DOWN", "KEY_VOLUMEUP", "KEY_VOLUMEDOWN"}


def is_cec(name):
    return name.startswith("vc4-hdmi") or name.startswith("cec")


def list_devices(text):
    """/proc/bus/input/devices -> [(name, eventN)]"""
    out = []
    for block in text.strip().split("\n\n"):
        name = re.search(r'^N: Name="(.*)"', block, re.M)
        handler = re.search(r"^H: Handlers=.*\b(event\d+)\b", block, re.M)
        if name and handler:
            out.append((name[1], handler[1]))
    return out


def decode(data):
    """Raw bytes from an event device -> [(type, code, value)]"""
    n = EVENT.size
    return [EVENT.unpack_from(data, i)[2:] for i in range(0, len(data) - n + 1, n)]


class InputReader:
    def __init__(self, device):
        self.device = device
        self.open = {}
        self.names = {}             # eventN -> device name

    def start(self):
        asyncio.ensure_future(self._watch())

    async def _watch(self):
        while True:
            try:
                devices = list_devices(Path("/proc/bus/input/devices").read_text())
            except OSError:
                devices = []
            for name, ev in devices:
                if name.endswith("(AVRCP)"):
                    continue                        # a phone's media keys (BlueZ uinput), not our remote
                if ev not in self.open:
                    self._attach(name, ev)
            await asyncio.sleep(10)                 # USB remotes may be plugged in later

    def _attach(self, name, ev):
        try:
            fd = os.open(f"/dev/input/{ev}", os.O_RDONLY | os.O_NONBLOCK)
        except OSError as exc:
            log.debug("cannot open %s: %s", ev, exc)
            return
        self.open[ev] = fd
        self.names[ev] = name
        log.info("input: %s (%s)", name, ev)
        asyncio.get_event_loop().add_reader(fd, self._read, ev, fd)

    def _read(self, ev, fd):
        try:
            data = os.read(fd, EVENT.size * 64)
        except BlockingIOError:
            return
        except OSError:
            asyncio.get_event_loop().remove_reader(fd)
            os.close(fd)
            self.open.pop(ev, None)
            return
        for etype, code, value in decode(data):
            try:
                self.handle(etype, code, value, self.names.get(ev, ""))
            except Exception:  # noqa: BLE001
                log.exception("input event")

    def handle(self, etype, code, value, source=""):
        d = self.device
        if is_cec(source):
            # TV remote: key names straight away; its scancodes are not IR codes to learn
            if etype == EV_KEY and value in (1, 2):
                name = CEC_KEYS.get(code)
                if name and (value == 1 or name in CEC_REPEATING):
                    d.on_cec_key(name)
            return
        if etype == EV_MSC and code == MSC_SCAN:
            d.on_ir(value & 0xFFFFFFFF)
        elif etype == EV_REL and value:
            d.on_encoder(1 if value > 0 else -1)
        elif etype == EV_KEY and value in (1, 2):
            name = KEYS.get(code)
            if name and (value == 1 or name in REPEATING):
                d.on_key(name)
