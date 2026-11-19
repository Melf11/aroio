"""HDMI-CEC: the Aroio as a playback device on the TV (vc4 HDMI, /dev/cec0 and /dev/cec1).

The kernel claims the logical address and turns the remote's keys into input events
(rc-cec keymap, devices "vc4-hdmi-N", read by aroiod/inputs.py -> Device.on_cec_key).
This module configures the adapters (cec-ctl: playback device, OSD name = device name)
and answers what TVs ask before they pass the remote on: active source after the input
was switched to the Aroio, power status, menu status. Everything else directed to us
gets a Feature Abort, as the CEC specification wants.
"""

import asyncio
import fcntl
import glob
import logging
import os
import struct
import unicodedata

log = logging.getLogger("aroiod.cec")

# linux/cec.h
MSG = struct.Struct("<QQIIII16sBBBBBBB")              # struct cec_msg (55 bytes, padded to 56)
MSG_SIZE = 56
CEC_TRANSMIT, CEC_RECEIVE = 0xC0386105, 0xC0386106
CEC_S_MODE, CEC_ADAP_G_PHYS_ADDR, CEC_ADAP_G_LOG_ADDRS = 0x40046109, 0x80026101, 0x805C6103
MODE = 0x01 | 0x10                                     # initiator + follower
BROADCAST = 0xF

FEATURE_ABORT, IMAGE_VIEW_ON, STANDBY = 0x00, 0x04, 0x36
UI_PRESSED, UI_RELEASED = 0x44, 0x45
ROUTING_CHANGE, ROUTING_INFORMATION, ACTIVE_SOURCE = 0x80, 0x81, 0x82
REQUEST_ACTIVE_SOURCE, SET_STREAM_PATH = 0x85, 0x86
MENU_REQUEST, MENU_STATUS = 0x8D, 0x8E
GIVE_DEVICE_POWER_STATUS, REPORT_POWER_STATUS = 0x8F, 0x90
INACTIVE_SOURCE = 0x9D
# answered by the kernel or not meant to be answered
NO_ABORT = {FEATURE_ABORT, UI_PRESSED, UI_RELEASED, 0x9F, 0x83, 0x8C, 0x46, 0xA5, 0x47, 0x84, 0x87, 0x9E,
            0x32, 0x8B, 0x89}
TV = 0


def osd_name(name):
    """CEC OSD names are ASCII, at most 14 characters."""
    text = name.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("Ä", "Ae") \
        .replace("Ö", "Oe").replace("Ü", "Ue").replace("ß", "ss")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return (text.strip() or "Aroio")[:14]


def pack(data):
    raw = MSG.pack(0, 0, len(data), 0, 0, 0, bytes(data).ljust(16, b"\0"), 0, 0, 0, 0, 0, 0, 0)
    return bytearray(raw.ljust(MSG_SIZE, b"\0"))


def unpack(buf):
    f = MSG.unpack_from(bytes(buf))
    return list(f[6][:f[2]])


class Adapter:
    """One HDMI port's CEC adapter, as a follower."""

    def __init__(self, path, device):
        self.path, self.device = path, device
        self.fd = None
        self.active = False         # the TV shows our input

    def physical_address(self):
        buf = bytearray(2)
        fcntl.ioctl(self.fd, CEC_ADAP_G_PHYS_ADDR, buf, True)
        return struct.unpack("<H", buf)[0]

    def logical_address(self):
        buf = bytearray(92)
        fcntl.ioctl(self.fd, CEC_ADAP_G_LOG_ADDRS, buf, True)
        la = buf[0]
        return la if la != 0xFF else None

    def open(self):
        self.fd = os.open(self.path, os.O_RDWR | os.O_NONBLOCK)
        fcntl.ioctl(self.fd, CEC_S_MODE, struct.pack("<I", MODE))
        asyncio.get_running_loop().add_reader(self.fd, self._readable)

    def close(self):
        if self.fd is not None:
            try:
                asyncio.get_running_loop().remove_reader(self.fd)
            except RuntimeError:
                pass
            os.close(self.fd)
            self.fd = None

    def send(self, data):
        try:
            fcntl.ioctl(self.fd, CEC_TRANSMIT, pack(data), True)
        except OSError as exc:              # no display, address not claimed yet, NACK
            log.debug("%s: transmit %s: %s", self.path, bytes(data).hex(), exc)

    def _readable(self):
        while True:
            buf = pack([])
            try:
                fcntl.ioctl(self.fd, CEC_RECEIVE, buf, True)
            except BlockingIOError:
                return
            except OSError as exc:
                log.debug("%s: receive: %s", self.path, exc)
                return
            try:
                self.handle(unpack(buf))
            except Exception:  # noqa: BLE001
                log.exception("CEC message")

    def handle(self, msg):
        """One received message (header, opcode, operands); answers through send()."""
        if len(msg) < 2:
            return
        src, dst, op, args = msg[0] >> 4, msg[0] & 0xF, msg[1], msg[2:]
        try:
            la, pa = self.logical_address(), self.physical_address()
        except OSError:
            return
        if la is None:
            return
        me = la << 4
        pa_bytes = [pa >> 8, pa & 0xFF]
        addr = (args[0] << 8 | args[1]) if len(args) >= 2 else None
        if op == SET_STREAM_PATH:
            self._set_active(addr == pa, pa_bytes, me)
        elif op == ROUTING_CHANGE and len(args) >= 4:
            self._set_active((args[2] << 8 | args[3]) == pa, pa_bytes, me)
        elif op == ROUTING_INFORMATION:
            self._set_active(addr == pa, pa_bytes, me)
        elif op == ACTIVE_SOURCE:
            if addr != pa and self.active:
                self.active = False
                log.info("%s: TV shows another input", self.path)
        elif op == REQUEST_ACTIVE_SOURCE:
            if self.active:
                self.send([me | BROADCAST, ACTIVE_SOURCE] + pa_bytes)
        elif dst == BROADCAST:
            return
        elif op == GIVE_DEVICE_POWER_STATUS:
            self.send([me | src, REPORT_POWER_STATUS, 0x00])                 # on
        elif op == MENU_REQUEST:
            self.send([me | src, MENU_STATUS, 0x00])                         # activated
        elif op not in NO_ABORT:
            self.send([me | src, FEATURE_ABORT, op, 0x00])                   # unrecognized opcode

    def _set_active(self, ours, pa_bytes, me):
        if ours:
            if not self.active:
                log.info("%s: TV switched to the Aroio", self.path)
            self.active = True
            self.send([me | BROADCAST, ACTIVE_SOURCE] + pa_bytes)
            # "our menu is active": many TVs (Panasonic VIERA Link) pass the remote's
            # keys only after this; Panasonic's own vendor command gets a Feature Abort
            self.send([me | TV, MENU_STATUS, 0x00])
        else:
            self.active = False


class Cec:
    """All CEC adapters of the device (Pi 4/5: two HDMI ports)."""

    def __init__(self, device, paths=None):
        self.device = device
        self.paths = paths if paths is not None else sorted(glob.glob("/dev/cec[0-9]*"))
        self.adapters = []

    async def start(self):
        if not self.paths:
            return
        await self.configure(self.device.config.get("device.name"))
        for path in self.paths:
            a = Adapter(path, self.device)
            try:
                a.open()
            except OSError as exc:
                log.warning("%s: %s", path, exc)
                continue
            self.adapters.append(a)
        log.info("CEC: %s as playback device", ", ".join(a.path for a in self.adapters) or "none")

    async def configure(self, name):
        """Playback device with the device name (the TV lists it as its input name)."""
        for path in self.paths:
            proc = await asyncio.create_subprocess_exec(
                "cec-ctl", "-d", path, "--playback", "--rc-src-dev-root", "--osd-name", osd_name(name),
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
            _, err = await proc.communicate()
            if proc.returncode:
                log.warning("cec-ctl %s: %s", path, err.decode(errors="replace").strip())
