"""Spotify Connect with Spotify Soloist, Spotify's own headless player.

librespot no longer gets audio keys for many accounts; Soloist does, but it is not part
of the image: every user enters their own Soloist API key (developer.spotify.com,
Einstellungen › Dienste › Spotify) and the Aroio downloads the player from Spotify.

- files: /data/spotify/bin/soloist (+ soloist.json: version, build date, ETag),
  /data/spotify/soloist (Soloist's own login), /data/aroio/soloist.env (SOLOIST_KEY, 0600)
- aroio-soloist.service runs it; sound goes through a minimal PulseAudio
  (aroio-pulse.service) into the loopback like every other player
- builds expire 90 days after they were made: aroio-soloist-update.timer fetches the
  newest one every 6 h (`python -m aroiod.soloist update`) and restarts the player only
  while nothing plays
- SoloistClient (in aroiod) talks to Soloist's WebSocket on 127.0.0.1:9090: what plays,
  title, cover, position, and play / pause / next / previous / seek from the Aroio

Protocol as used by Tapedeck (same author): commands {"type": "command", "command": …},
events auth_state, playback_state, track_changed, playback_changed, position_sync, …
"""

import asyncio
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

log = logging.getLogger("aroiod.soloist")

DIR = Path(os.environ.get("AROIO_SPOTIFY_DIR", "/data/spotify"))
BIN = DIR / "bin" / "soloist"
INFO = DIR / "bin" / "soloist.json"
PENDING = DIR / "bin" / "soloist.pending"       # new build waits for a moment without music
ENV = Path(os.environ.get("AROIO_SOLOIST_ENV", "/data/aroio/soloist.env"))
UNIT = "aroio-soloist.service"
WS = os.environ.get("AROIO_SOLOIST_WS", "ws://127.0.0.1:9090")
DOWNLOAD = "https://soloist-builds.spotifycdn.com/soloist_release_{arch}.tar.gz"
BUILD_LIFETIME_DAYS = 90
RATE = 44100


def clean_key(value):
    key = "".join(str(value or "").split())
    if len(key) < 16 or not key.isprintable() or '"' in key or "\\" in key:
        raise ValueError("Der Schlüssel ist unvollständig. Bitte ihn vollständig kopieren und einfügen.")
    return key


def write_key(key):
    """Key for the systemd unit (EnvironmentFile), readable by root only."""
    ENV.parent.mkdir(parents=True, exist_ok=True)
    tmp = ENV.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(f'SOLOIST_KEY="{key}"\n')
    os.replace(tmp, ENV)


def remove_key():
    ENV.unlink(missing_ok=True)


def info():
    """Installed player: version, build date, expiry (for the app)."""
    try:
        data = json.loads(INFO.read_text())
    except (OSError, ValueError):
        data = {}
    data["installed"] = BIN.is_file()
    if data.get("build_date"):
        try:
            built = time.mktime(time.strptime(data["build_date"], "%Y%m%d"))
            data["expires"] = time.strftime("%Y-%m-%d", time.localtime(built + BUILD_LIFETIME_DAYS * 86400))
        except ValueError:
            pass
    return data


def arch():
    return {"aarch64": "arm64", "arm64": "arm64", "armv7l": "arm32", "x86_64": "x86_64"}.get(platform.machine())


def parse_version(line):
    """'soloist 1.3.10.71 build … (20261113) …' -> ('1.3.10.71', '20261113')"""
    import re
    m = re.search(r"soloist\s+([\d.]+).*?\((\d{8})\)", line or "")
    return (m.group(1), m.group(2)) if m else (None, None)


def _open(req, timeout):
    """urlopen with the proxy as it is now: urllib.request.urlopen builds its opener once and
    keeps the proxy of that moment, so a proxy entered later would be ignored."""
    from . import proxy
    https = urllib.request.HTTPSHandler(context=proxy.ssl_context())   # company certificate, if any
    return urllib.request.build_opener(https).open(req, timeout=timeout)


def _idle(settle=10.0):
    """Nothing plays on Soloist (or it is not running): safe to restart it. Asked twice,
    `settle` seconds apart: right after someone picks the Aroio in the Spotify app it is
    the active device but not yet "playing" (a restart then left it playing into nothing)."""
    if not _idle_now():
        return False
    time.sleep(settle)
    return _idle_now()


def _idle_now():
    async def ask():
        import aiohttp
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as s:
                async with s.ws_connect(WS) as ws:
                    await ws.send_json({"type": "command", "command": "get_state"})
                    async for msg in ws:
                        data = json.loads(msg.data)
                        if data.get("type") == "playback_state":
                            status = data.get("status")
                            starting = data.get("is_active") and status not in ("paused",)
                            return status not in ("playing", "buffering") and not starting
        except Exception:  # noqa: BLE001 — not running counts as idle
            return True
        return True
    return asyncio.run(ask())


def update(force=False):
    """Fetch a newer Soloist if Spotify has one; returns a short German message."""
    if not ENV.exists() and not force:
        return "Spotify ist nicht eingerichtet."
    a = arch()
    if not a:
        return f"Für diese Architektur ({platform.machine()}) gibt es Soloist nicht."
    url = DOWNLOAD.format(arch=a)
    current = info()
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "AroioOS"})
        with _open(req, 20) as res:
            etag = res.headers.get("ETag") or res.headers.get("Last-Modified")
    except (urllib.error.URLError, OSError) as exc:
        return f"Spotify-Download nicht erreichbar: {exc}"
    message = "Soloist ist aktuell."
    if force or not BIN.is_file() or etag != current.get("etag"):
        BIN.parent.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix="soloist-", dir=BIN.parent))
        try:
            archive = work / "soloist.tar.gz"
            req = urllib.request.Request(url, headers={"User-Agent": "AroioOS"})
            with _open(req, 180) as res, open(archive, "wb") as out:
                shutil.copyfileobj(res, out)
            with tarfile.open(archive) as tar:
                member = tar.getmember("soloist")
                if not member.isfile():
                    raise RuntimeError("kein Programm im Archiv")
                tar.extract(member, work, filter="data")
            binary = work / "soloist"
            binary.chmod(0o755)
            out = subprocess.run([str(binary), "--version"], capture_output=True, text=True, timeout=30)
            if out.returncode != 0:
                raise RuntimeError(out.stderr.strip() or f"Exit {out.returncode}")
            line = (out.stdout.strip().splitlines() or [""])[0]
            version, build_date = parse_version(line)
            os.replace(binary, BIN)
            tmp = INFO.with_suffix(".tmp")
            tmp.write_text(json.dumps({"etag": etag, "version": version, "build_date": build_date,
                                       "line": line, "updated": time.time()}))
            os.replace(tmp, INFO)
            PENDING.touch()
            message = f"Soloist {version or ''} ({build_date or '?'}) geladen."
            log.info(message)
        except Exception as exc:  # noqa: BLE001
            return f"Soloist-Update fehlgeschlagen: {exc}"
        finally:
            shutil.rmtree(work, ignore_errors=True)
    if PENDING.exists():
        if _idle():
            PENDING.unlink(missing_ok=True)
            subprocess.run(["systemctl", "restart", UNIT], check=False, timeout=60)
            message += " Spotify-Player neu gestartet."
        else:
            message += " Neustart folgt, wenn gerade nichts läuft."
    return message


# ── what Soloist reports -> the app's track ──────────────────────────────────

def _names(entities):
    return ", ".join(n for n in (((e or {}).get("entity") or {}).get("decorations", {}).get("identity", {}).get("name", "")
                                  for e in entities or [] if e) if n)


def _cover(item):
    covers = ((item or {}).get("decorations") or {}).get("visual_identity", {}).get("cover") or []
    best = next((c for c in covers if c.get("size") == "large"), None) or \
        next((c for c in covers if c.get("size") == "default"), None) or (covers[0] if covers else None)
    return (best or {}).get("url")


def track_meta(item, position=None):
    """Soloist item (+ position) -> meta in the shape of the app (see sim._external_meta)."""
    item = item or {}
    identity = (item.get("decorations") or {}).get("identity") or {}
    duration = ((item.get("playback") or {}).get("duration_ms") or 0) / 1000.0
    meta = {"id": item.get("uri") or "spotify", "title": identity.get("name") or "Spotify",
            "artist": _names(item.get("creators")), "album": _names([item.get("parent")]) if item.get("parent") else "",
            "duration": round(duration, 1), "image": _cover(item), "provider": "spotify", "live": not duration,
            "format": {"codec": "Vorbis/AAC", "bits": 16, "rate": RATE}}
    if position:
        ms = position.get("position_ms") or 0
        if position.get("speed") and position.get("timestamp_ms"):
            ms += max(0, time.time() * 1000 - position["timestamp_ms"]) * position["speed"]
        meta["position"] = round(ms / 1000.0, 1)
    return meta


class SoloistClient:
    """Mirrors Soloist into the Device: start/stop/pause, track info; sends commands."""

    def __init__(self, device, url=WS):
        self.device, self.url = device, url
        self.ws = None
        self.connected = self.logged_in = False
        self.status = None              # idle / playing / paused / buffering
        self.active = False             # the Aroio is the selected Spotify device
        self.item = None
        self.position = None
        self.error = None

    def start(self):
        asyncio.ensure_future(self._run())

    def _publish(self):
        """Settings › Spotify shows connected / logged in."""
        publish = getattr(self.device, "publish_services", None)
        if publish:
            publish()

    async def _run(self):
        import aiohttp
        quiet = False
        while True:
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.ws_connect(self.url, heartbeat=30) as ws:
                        self.ws, self.connected, quiet = ws, True, False
                        log.info("Soloist verbunden")
                        self._publish()
                        await self.send("get_auth_state")
                        async for msg in ws:
                            if msg.type != aiohttp.WSMsgType.TEXT:
                                break
                            try:
                                await self.handle(json.loads(msg.data))
                            except (ValueError, TypeError, AttributeError) as exc:
                                log.debug("Soloist message: %s", exc)
            except (aiohttp.ClientError, OSError) as exc:
                if not quiet:
                    log.info("Soloist nicht erreichbar (%s)", exc)
                    quiet = True
            finally:
                if self.connected:
                    self.connected = self.logged_in = False
                    self._stopped()
                    self._publish()
                self.ws = None
            await asyncio.sleep(3)

    async def send(self, command, **fields):
        if self.ws is None or self.ws.closed:
            return False
        await self.ws.send_json({"type": "command", "command": command, **fields})
        return True

    async def handle(self, msg):
        kind = msg.get("type")
        if kind == "auth_state":
            was = self.logged_in
            self.logged_in = bool(msg.get("logged_in"))
            self.active = bool(msg.get("is_active"))
            if was != self.logged_in:
                self._publish()
            if self.logged_in:
                await self.send("get_state")
            return
        if kind == "playback_state":
            if "item" in msg:
                self.item = self._merge(msg["item"])
            self.position = msg.get("position", self.position)
            self.active = bool(msg.get("is_active", self.active))
            self._status(msg.get("status"))
            self._meta()
        elif kind == "track_changed":
            self.item = self._merge(msg.get("item"))
            self._meta()
            await self.send("get_state")           # track info is often incomplete
        elif kind == "playback_changed":
            self._status(msg.get("status"))
        elif kind == "position_sync":
            self.position = msg.get("position")
            self._meta()
        elif kind == "device_changed":
            self.active = bool(msg.get("is_active"))
            if not self.active:
                self._stopped()
        elif kind == "error":
            self.error = msg.get("message")
            log.info("Soloist: %s", self.error)

    def _merge(self, item):
        if item and self.item and item.get("uri") == self.item.get("uri"):
            return {**self.item, **item}
        return item

    def _status(self, status):
        if status is None:
            return
        before, self.status = self.status, status
        d = self.device
        if status in ("playing", "buffering"):
            if d.source != "spotify":
                d.source_started("spotify", track_meta(self.item, self.position), rate=RATE)
            elif before not in ("playing", "buffering"):
                d.source_resumed("spotify")
        elif status == "paused":
            d.source_paused("spotify")
        elif status == "idle":
            self._stopped()

    def _stopped(self):
        if self.device.source == "spotify":
            self.device.source_stopped("spotify")

    def _meta(self):
        if self.item:
            self.device.external_meta("spotify", track_meta(self.item, self.position))

    # ── commands from the Aroio (player buttons, IR, encoder) ──
    async def command(self, cmd, value=None):
        names = {"play": "play", "pause": "pause", "next": "skip_next", "previous": "skip_prev"}
        if cmd == "seek":
            return await self.send("seek", position_ms=max(0, int(value * 1000)))
        return await self.send(names[cmd])


def main():
    logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s: %(message)s")
    if len(sys.argv) > 1 and sys.argv[1] == "update":
        print(update(force="--force" in sys.argv))
    else:
        print("Aufruf: python -m aroiod.soloist update [--force]")
        sys.exit(2)


if __name__ == "__main__":
    main()
