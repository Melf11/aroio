"""Bluetooth playback on the device -> Device.source_started/stopped/external_meta.

bluealsa-aplay plays every A2DP stream into the loopback but tells nobody.
This watcher asks BlueALSA which sink PCMs are running (`bluealsa-cli`) and
BlueZ for the AVRCP track of the phone (MediaPlayer1.Track via busctl). It
also sends AVRCP pause when another source takes over.
"""

import asyncio
import json
import logging
import re

log = logging.getLogger("aroiod.bt")

PCM = re.compile(r"^/org/bluealsa/(hci\d+)/dev_([0-9A-F_]{17})/a2dpsnk/source$")


def parse_pcms(text):
    """`bluealsa-cli list-pcms` -> [(path, "AA:BB:...")] for A2DP sink streams."""
    out = []
    for line in text.split():
        m = PCM.match(line.strip())
        if m:
            out.append((line.strip(), m[2].replace("_", ":")))
    return out


def parse_running(info):
    """`bluealsa-cli info <pcm>` -> True/False (line "Running: true")."""
    m = re.search(r"^Running:\s*(\w+)", info, re.M)
    return bool(m and m[1].lower() in ("true", "yes", "1"))


def parse_codec(info):
    m = re.search(r"^Selected codec:\s*([\w-]+)", info, re.M) or re.search(r"^Codec:\s*([\w-]+)", info, re.M)
    rate = re.search(r"^(?:Rate|Sampling):\s*(\d+)", info, re.M)
    return (m[1] if m else None), (int(rate[1]) if rate else None)


def parse_volume(info):
    """"Volume: L: 127 R: 127" (A2DP 0..127) -> percent, None if unknown."""
    m = re.search(r"^Volume:\s*L:\s*(\d+)\s*R:\s*(\d+)", info, re.M) or re.search(r"^Volume:\s*(\d+)", info, re.M)
    if not m:
        return None
    return round(max(int(v) for v in m.groups()) / 127 * 100)


def parse_track(busctl_json):
    """busctl --json=short get-property ... Track -> {title, artist, album, duration}"""
    try:
        data = json.loads(busctl_json)["data"]
    except (ValueError, KeyError, TypeError):
        return {}
    val = lambda k: (data.get(k) or {}).get("data")  # noqa: E731
    out = {"title": val("Title") or "", "artist": val("Artist") or "", "album": val("Album") or ""}
    if val("Duration"):
        out["duration"] = round(int(val("Duration")) / 1000.0, 1)
    return out


async def _out(*cmd, timeout=4):
    try:
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.DEVNULL)
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
        return out.decode("utf-8", "replace") if proc.returncode == 0 else ""
    except (OSError, asyncio.TimeoutError):
        return ""


async def _ok(*cmd, timeout=4):
    try:
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL,
                                                    stderr=asyncio.subprocess.DEVNULL)
        return await asyncio.wait_for(proc.wait(), timeout) == 0
    except (OSError, asyncio.TimeoutError):
        return False


class BluetoothWatch:
    INTERVAL = 1.0
    STOP_AFTER = 3.0          # seconds without a running stream before "stopped"

    def __init__(self, device):
        self.device = device
        self.active = None    # (pcm path, address) while playing
        self.idle_since = None
        self.meta_key = None
        self.suppressed = False   # paused for another source: ignore until the stream stops once
        self.volume = None        # last volume the phone set (percent)
        self.address = None       # last phone that played: play/next/previous go there

    def start(self):
        asyncio.ensure_future(self._run())

    async def _run(self):
        while True:
            try:
                await self.poll()
            except Exception:  # noqa: BLE001
                log.exception("bluetooth watch")
            await asyncio.sleep(self.INTERVAL)

    async def poll(self):
        running = None
        for path, addr in parse_pcms(await _out("bluealsa-cli", "list-pcms")):
            info = await _out("bluealsa-cli", "info", path)
            if parse_running(info):
                running = (path, addr, info)
                break
        d = self.device
        loop = asyncio.get_running_loop()
        if self.suppressed:
            if running and d.source != "bluetooth":
                return
            self.suppressed = False
        if running:
            self.idle_since = None
            path, addr, info = running
            meta = await self.meta(addr, info)
            key = json.dumps(meta, sort_keys=True)
            if self.active != (path, addr) or d.source != "bluetooth":
                self.active = (path, addr)
                self.address = addr
                self.meta_key = key
                d.source_started("bluetooth", meta, rate=meta["format"]["rate"])
            elif key != self.meta_key:
                self.meta_key = key
                d.external_meta("bluetooth", meta)
            vol = parse_volume(info)
            if vol is not None and vol != self.volume:
                if self.volume is not None:      # a change on the phone, not the first look
                    d.remote_volume(vol)
                self.volume = vol
        elif self.active:
            if self.idle_since is None:
                self.idle_since = loop.time()
            elif loop.time() - self.idle_since > self.STOP_AFTER:
                self.active = None
                d.source_stopped("bluetooth")

    async def meta(self, addr, info):
        codec, rate = parse_codec(info)
        dev_path = f"/org/bluez/hci0/dev_{addr.replace(':', '_')}"
        name = ""
        alias = await _out("busctl", "--json=short", "get-property", "org.bluez", dev_path, "org.bluez.Device1", "Alias")
        try:
            name = json.loads(alias)["data"]
        except (ValueError, KeyError, TypeError):
            pass
        track = {}
        for player in ("player0", "player1"):
            raw = await _out("busctl", "--json=short", "get-property", "org.bluez", f"{dev_path}/{player}",
                             "org.bluez.MediaPlayer1", "Track")
            if raw:
                track = parse_track(raw)
                break
        return {"id": f"bluetooth:{addr}:{track.get('title', '')}", "title": track.get("title") or name or "Bluetooth",
                "artist": track.get("artist", ""), "album": track.get("album", ""),
                "duration": track.get("duration", 0), "image": None, "provider": "bluetooth",
                "controller": name or addr, "live": not track.get("duration"),
                "format": {"codec": (codec or "SBC").upper(), "bits": 16, "rate": rate or 44100}}

    async def command(self, cmd):
        """AVRCP play / next / previous on the phone that played last. True if sent."""
        if not self.address:
            return False
        method = {"play": "Play", "next": "Next", "previous": "Previous", "pause": "Pause"}[cmd]
        dev_path = f"/org/bluez/hci0/dev_{self.address.replace(':', '_')}"
        for player in ("player0", "player1"):
            if await _ok("busctl", "call", "org.bluez", f"{dev_path}/{player}", "org.bluez.MediaPlayer1", method):
                return True
        # phones without a media player object: the older MediaControl1
        return await _ok("busctl", "call", "org.bluez", dev_path, "org.bluez.MediaControl1", method)

    async def pause(self):
        """AVRCP pause on the phone (another source started)."""
        if not self.active:
            return
        self.suppressed = True
        dev_path = f"/org/bluez/hci0/dev_{self.active[1].replace(':', '_')}"
        for player in ("player0", "player1"):
            if await _ok("busctl", "call", "org.bluez", f"{dev_path}/{player}", "org.bluez.MediaPlayer1", "Pause"):
                return
        await _ok("busctl", "call", "org.bluez", dev_path, "org.bluez.MediaControl1", "Pause")
