"""AirPlay metadata from shairport-sync (metadata pipe) -> title, artist, album, cover.

shairport-sync writes items like

    <item><type>636f7265</type><code>6d696e6d</code><length>5</length>
    <data encoding="base64">
    SGFsbG8=</data></item>

type/code are 4 ASCII characters in hex: "core" items carry DAAP fields
(minm title, asar artist, asal album, astm duration in ms), "ssnc" items come
from shairport itself (PICT cover, prgr progress, pbeg/pend play begin/end,
pfls/prsm pause/resume, snam name of the sending device, mden end of a
metadata block, daid/acre/clip what the Aroio needs to remote-control the sender).
Parsing is pure and testable; the pipe reader lives in AirplayMeta.

Remote control: Shairport Sync 5.6 controls AirPlay 2 senders through its D-Bus
interface (org.gnome.ShairportSync.RemoteControl: Play, Pause, Next, Previous); its
"Available" property stays false in AirPlay 2 although the commands work, so aroiod
uses it whenever the bus name exists. Older senders (classic AirPlay) also work over
DACP: the sender (iPhone, Mac) announces iTunes_Ctrl_<daid> as
_dacp._tcp over mDNS; GET /ctrl-int/1/<command> with the header Active-Remote: <acre>
plays, pauses or skips there. That keeps the AirPlay session, unlike restarting
shairport-sync.
"""

import asyncio
import base64
import hashlib
import logging
import os
import re
import stat
from pathlib import Path

log = logging.getLogger("aroiod.airplay")

PIPE = "/run/shairport-sync/metadata"
ITEM = re.compile(rb"<item><type>([0-9a-f]{8})</type><code>([0-9a-f]{8})</code><length>(\d+)</length>"
                  rb"(?:\s*<data encoding=\"base64\">\s*([A-Za-z0-9+/=\s]*?)</data>)?\s*</item>")


def _ascii(hexstr):
    return bytes.fromhex(hexstr.decode()).decode("ascii", "replace")


def parse(buffer):
    """bytes -> ([(type, code, payload bytes)], rest of buffer not yet complete)"""
    items, end = [], 0
    for m in ITEM.finditer(buffer):
        payload = base64.b64decode(re.sub(rb"\s", b"", m[4])) if m[4] else b""
        items.append((_ascii(m[1]), _ascii(m[2]), payload))
        end = m.end()
    rest = buffer[end:]
    if len(rest) > 8 * 1024 * 1024:        # garbage, never a valid item: start over
        rest = b""
    return items, rest


def image_type(data):
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    return None


class Track:
    """Collects items into the meta shape of the app (see sim._external_meta)."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.title = self.artist = self.album = ""
        self.duration = 0.0
        self.position = None
        self.cover = None              # (content type, bytes)
        self.controller = None
        self.volume = None
        self.remote = {}               # daid, acre, clip: remote control of the sender

    def feed(self, typ, code, data):
        """Returns an event: "meta" (new values to show), "start", "stop", "pause", "resume" or None."""
        text = lambda: data.decode("utf-8", "replace").strip()  # noqa: E731
        if typ == "core":
            if code == "minm":
                self.title = text()
            elif code == "asar":
                self.artist = text()
            elif code == "asal":
                self.album = text()
            elif code == "astm" and len(data) == 4:
                self.duration = int.from_bytes(data, "big") / 1000.0
            return None
        if typ != "ssnc":
            return None
        if code == "mden":
            return "meta"
        if code == "PICT":
            kind = image_type(data)
            self.cover = (kind, data) if kind else None
            return "meta"
        if code == "prgr":
            try:
                start, cur, end = (int(x) for x in text().split("/"))
            except ValueError:
                return None
            span = (end - start) & 0xFFFFFFFF
            if span:
                self.duration = span / 44100.0
                self.position = ((cur - start) & 0xFFFFFFFF) / 44100.0
            return "meta"
        if code == "pvol":
            # "airplay_volume,volume,lowest,highest": airplay_volume -30 (quiet) .. 0, -144 = mute
            try:
                av = float(text().split(",")[0])
            except ValueError:
                return None
            self.volume = 0.0 if av <= -144 else max(0.0, min(100.0, (av + 30.0) / 30.0 * 100.0))
            return "volume"
        if code == "snam":
            self.controller = text() or None
            return None
        if code in ("daid", "acre", "clip"):
            self.remote[code] = text()
            return None
        return {"pbeg": "start", "pend": "stop", "pfls": "pause", "prsm": "resume"}.get(code)

    def cover_id(self):
        return hashlib.sha1(self.cover[1]).hexdigest()[:12] if self.cover else None

    def meta(self):
        cid = self.cover_id()
        m = {"id": f"airplay:{cid or self.title}", "title": self.title or "AirPlay", "artist": self.artist,
             "album": self.album, "duration": round(self.duration, 1),
             "image": f"/api/v1/cover/airplay?v={cid}" if cid else None,
             "format": {"codec": "ALAC", "bits": 16, "rate": 44100}, "provider": "airplay",
             "controller": self.controller, "live": not self.duration}
        if self.position is not None:
            m["position"] = round(self.position, 1)
        return m


class AirplayMeta:
    """Reads the shairport-sync metadata pipe on the device and reports to the Device."""

    def __init__(self, device, path=PIPE):
        self.device = device
        self.path = Path(path)
        self.track = Track()
        self._buf = b""
        self._pending = None
        self._dacp = {}                # daid -> (host, port)
        self.dbus = False              # Shairport Sync D-Bus remote control seen

    def start(self):
        asyncio.ensure_future(self._run())
        asyncio.ensure_future(self.probe_dbus())

    async def _run(self):
        while True:
            try:
                await self._read_pipe()
            except Exception as exc:  # noqa: BLE001
                log.debug("metadata pipe: %s", exc)
            await asyncio.sleep(2)

    async def _read_pipe(self):
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            os.mkfifo(self.path, 0o666)
        if not stat.S_ISFIFO(self.path.stat().st_mode):
            return
        # O_RDWR keeps the FIFO open when shairport-sync restarts (no EOF busy loop)
        fd = os.open(self.path, os.O_RDWR | os.O_NONBLOCK)
        loop = asyncio.get_event_loop()
        closed = loop.create_future()

        def readable():
            try:
                chunk = os.read(fd, 65536)
            except BlockingIOError:
                return
            except OSError as exc:
                if not closed.done():
                    closed.set_exception(exc)
                return
            self.handle_bytes(chunk)

        loop.add_reader(fd, readable)
        try:
            await closed
        finally:
            loop.remove_reader(fd)
            os.close(fd)

    def handle_bytes(self, chunk):
        items, self._buf = parse(self._buf + chunk)
        for typ, code, data in items:
            event = self.track.feed(typ, code, data)
            if event:
                self.handle_event(event)

    def handle_event(self, event):
        d = self.device
        if event == "start":
            self.track.position = None
            log.info("AirPlay from %s, DACP: %s", self.track.controller,
                     "yes" if self.track.remote.get("acre") else "no")
            if _loop_running():
                asyncio.ensure_future(self._probe_and_publish())
            d.source_started("airplay", self.track.meta(), rate=44100)
        elif event == "stop":
            d.source_stopped("airplay")
            remote = self.track.remote
            self.track.reset()
            self.track.remote = remote        # the sender stays connected (pause): keep its remote
        elif event == "pause":
            d.source_paused("airplay")
        elif event == "resume":
            d.source_resumed("airplay")
        elif event == "volume":
            if d.source == "airplay" and self.track.volume is not None:
                d.remote_volume(self.track.volume)
        elif event == "meta":
            # several items arrive at once: report once per burst
            if not _loop_running():
                self._send()
            elif self._pending is None:
                self._pending = asyncio.get_running_loop().call_later(0.15, self._send)

    async def _probe_and_publish(self):
        before = self.dbus
        await self.probe_dbus()
        if self.dbus != before:
            self.device.publish_player()          # the buttons depend on it

    def _send(self):
        self._pending = None
        self.device.external_meta("airplay", self.track.meta())

    def cover(self):
        return self.track.cover

    # ── remote control ──
    DBUS = ("org.gnome.ShairportSync", "/org/gnome/ShairportSync", "org.gnome.ShairportSync.RemoteControl")
    DBUS_METHODS = {"play": "Play", "pause": "Pause", "playpause": "PlayPause", "nextitem": "Next", "previtem": "Previous"}

    def can_control(self):
        return bool(self.dbus or self.track.remote.get("acre"))

    async def probe_dbus(self):
        """Is Shairport Sync's D-Bus interface there (5.6 with --with-dbus-interface)?"""
        ok, _ = await _exec("busctl", "--system", "status", self.DBUS[0])
        if ok != self.dbus:
            self.dbus = ok
            log.info("AirPlay remote control over D-Bus: %s", "yes" if ok else "no")
        return ok

    async def command(self, cmd):
        """Command to the sender: play, pause, playpause, nextitem, previtem. True if sent."""
        if self.dbus or await self.probe_dbus():
            ok, out = await _exec("busctl", "--system", "call", *self.DBUS, self.DBUS_METHODS[cmd])
            if ok:
                return True
            log.info("AirPlay %s over D-Bus: %s", cmd, out.strip())
        return await self._dacp_command(cmd)

    async def _dacp_command(self, cmd):
        """DACP to the sender (classic AirPlay)."""
        r = self.track.remote
        if not r.get("daid") or not r.get("acre"):
            log.info("AirPlay: sender has no remote control (%s)", cmd)
            return False
        target = self._dacp.get(r["daid"]) or await self._resolve(r["daid"], r.get("clip"))
        if not target:
            log.info("AirPlay: iTunes_Ctrl_%s not found", r["daid"])
            return False
        self._dacp[r["daid"]] = target
        host, port = target
        url = f"http://{'[' + host + ']' if ':' in host else host}:{port}/ctrl-int/1/{cmd}"
        import aiohttp
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3)) as s:
                async with s.get(url, headers={"Active-Remote": r["acre"]}) as resp:
                    ok = resp.status in (200, 204)
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError) as exc:
            log.info("AirPlay %s: %s", cmd, exc)
            self._dacp.pop(r["daid"], None)          # port may have changed: look again next time
            return False
        if not ok:
            log.info("AirPlay %s: HTTP %s", cmd, resp.status)
        return ok

    async def _resolve(self, daid, clip):
        proc = await asyncio.create_subprocess_exec(
            "avahi-browse", "-rpt", "_dacp._tcp", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), 5)
        except asyncio.TimeoutError:
            proc.kill()
            return None
        return pick_dacp(out.decode(errors="replace"), daid, clip)


async def _exec(*cmd):
    try:
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        out, _ = await asyncio.wait_for(proc.communicate(), 4)
    except (OSError, asyncio.TimeoutError) as exc:
        return False, str(exc)
    return proc.returncode == 0, out.decode(errors="replace")


def pick_dacp(browse, daid, clip=None):
    """avahi-browse -rpt output -> (address, port) of iTunes_Ctrl_<daid>; the sender's own
    address (clip) first, then IPv4, then the rest (IPv6 link-local needs no zone here)."""
    found = []
    for line in browse.splitlines():
        f = line.split(";")
        if len(f) >= 9 and f[0] == "=" and f[3].upper() == f"ITUNES_CTRL_{daid}".upper() and f[8].isdigit():
            addr = f[7]
            if addr.startswith("fe80"):
                addr = f"{addr}%{f[1]}"
            found.append((addr != clip, f[2] != "IPv4", addr, int(f[8])))
    if not found:
        return None
    _, _, addr, port = min(found)
    return addr, port


def _loop_running():
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False
