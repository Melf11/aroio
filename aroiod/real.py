"""The real world on a Raspberry Pi: CamillaDSP, ALSA, systemd, network.

Same interface as aroiod.sim.SimWorld. Phase 1 status:
- done:     CamillaDSP control (config, volume, mute, load, rate changes), DAC and
            measurement microphone detection, test tone, room measurement with
            aplay/arecord, network status, board detection, reboot
- minimal:  sources (systemd units on/off, events from player hooks via
            /api/v1/internal/source), Spotify/Lyrion/Bluetooth status
- missing:  BlueZ/iwd D-Bus, TIDAL/Qobuz login (Lyrion plugins)
"""

import asyncio
import json
import logging
import os
import re
import subprocess
import tempfile
import time
import wave
from pathlib import Path

import aiohttp
import numpy as np

log = logging.getLogger("aroiod.real")

CAMILLA_URL = "ws://127.0.0.1:1234"
LOOPBACK_PLAY = "plughw:Loopback,0,0"  # players and aroiod's own signals write here (plug: format/rate of CamillaDSP)
SOURCE_UNITS = {"lms": "squeezelite.service", "spotify": "aroio-spotify.service",
                "airplay": "shairport-sync.service", "upnp": "upmpdcli.service",
                "bluetooth": "bluealsa-aplay.service", "roon": "roonbridge.service",
                "netjack": "aroio-netjack.service"}


# ── ALSA ─────────────────────────────────────────────────────────────────────

def parse_cards(text):
    """/proc/asound/cards -> [{"index", "id", "driver", "name"}]"""
    cards = []
    for m in re.finditer(r"^\s*(\d+)\s+\[(\S+)\s*\]:\s*(\S+)\s+-\s+(.*)$", text, re.M):
        cards.append({"index": int(m[1]), "id": m[2], "driver": m[3], "name": m[4].strip()})
    return cards


def read_cards():
    try:
        return parse_cards(Path("/proc/asound/cards").read_text())
    except OSError:
        return []


def find_dac(cards, preferred=""):
    """The output device: configured name, else the first I2S/HAT DAC, else a USB DAC
    that is not a measurement microphone, else HDMI."""
    if preferred and preferred != "auto":
        return preferred
    ignore = ("Loopback", "Headphones")
    def is_mic(c):
        return bool(re.search(r"umik|minidsp|mic", c["name"] + c["id"], re.I))
    hats = [c for c in cards if c["id"] not in ignore and not c["id"].startswith("vc4hdmi") and c["driver"] != "USB-Audio"]
    usb = [c for c in cards if c["driver"] == "USB-Audio" and not is_mic(c)]
    hdmi = [c for c in cards if c["id"].startswith("vc4hdmi")]
    for group in (hats, usb, hdmi):
        if group:
            return f"hw:CARD={group[0]['id']},DEV=0"
    return "hw:0,0"


def output_kind(card):
    if card["driver"] == "USB-Audio":
        return "usb"
    if card["id"].startswith("vc4hdmi") or "HDMI" in card["name"]:
        return "hdmi"
    if card["id"] == "Headphones" or card["driver"].startswith("bcm2835"):
        return "analog"
    return "hat"


CARD_NAMES = {"IQaudIODAC": "Raspberry Pi DAC+ (IQaudio)", "IQaudIOCODEC": "Raspberry Pi Codec Zero (IQaudio)",
              "DigiAMP": "Raspberry Pi DigiAMP+", "sndrpihifiberry": "HiFiBerry", "AroioDAC": "Aroio DAC",
              "BossDAC": "Allo Boss DAC"}


def list_outputs(cards, driver=None):
    """Every card that can play music: no loopback, no measurement microphone.
    Names people understand instead of the kernel's card ids."""
    out = []
    for c in cards:
        if c["id"] == "Loopback" or find_mic([c]):
            continue
        kind = output_kind(c)
        name = "Aroio DAC" if kind == "hat" and driver == "aroio" else CARD_NAMES.get(c["id"], c["name"])
        out.append({"id": f"hw:CARD={c['id']},DEV=0", "name": name, "card": c["id"], "kind": kind})
    order = {"hat": 0, "usb": 1, "analog": 2, "hdmi": 3}
    return sorted(out, key=lambda o: (order[o["kind"]], o["card"]))


def resolve_output(cards, preferred):
    """The configured output if it is present, else the automatic choice."""
    if preferred and preferred != "auto" and any(o["id"] == preferred for o in list_outputs(cards)):
        return preferred
    return find_dac(cards)


def iwd_profile_name(ssid, secure=True):
    """iwd's file name for a known network: plain SSID if it is simple, else '=' + hex."""
    if re.fullmatch(r"[A-Za-z0-9_-]+", ssid):
        base = ssid
    else:
        base = "=" + ssid.encode().hex()
    return base + (".psk" if secure else ".open")


def write_iwd_profile(directory, ssid, psk):
    path = Path(directory) / iwd_profile_name(ssid, bool(psk))
    path.parent.mkdir(parents=True, exist_ok=True)
    text = f"[Security]\nPassphrase={psk}\n" if psk else "[Settings]\nAutoConnect=true\n"
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    return path


def parse_bt_devices(text):
    """`bluetoothctl devices [Paired|Connected]` -> [{"address", "name"}]"""
    out = []
    for line in text.splitlines():
        m = re.match(r"^Device ([0-9A-F:]{17}) (.*)$", line.strip())
        if m:
            out.append({"address": m[1], "name": m[2]})
    return out


def find_mic(cards):
    for c in cards:
        if c["driver"] == "USB-Audio" and re.search(r"umik|minidsp", c["name"] + c["id"], re.I):
            return c
    return None


def write_wav(path, data, rate=48000, channels=1):
    pcm = np.clip(data, -1, 1)
    pcm = (pcm * 2147483647).astype("<i4")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(4)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def read_wav(path):
    with wave.open(str(path), "rb") as w:
        width, ch, n = w.getsampwidth(), w.getnchannels(), w.getnframes()
        raw = w.readframes(n)
    dtype = {2: "<i2", 4: "<i4"}[width]
    data = np.frombuffer(raw, dtype=dtype).astype(np.float64) / (2 ** (8 * width - 1))
    return data.reshape(-1, ch)[:, 0]


def stereo(signal, channel):
    out = np.zeros((len(signal), 2))
    if channel in ("L", "both"):
        out[:, 0] = signal
    if channel in ("R", "both"):
        out[:, 1] = signal
    return out.reshape(-1)


# ── CamillaDSP ───────────────────────────────────────────────────────────────

class CamillaClient:
    """Websocket client for CamillaDSP 4. One connection, commands are serialised;
    reconnects on its own. Commands sent while CamillaDSP is down are dropped,
    the current config is sent again after every reconnect."""

    def __init__(self, url=CAMILLA_URL, on_rate_change=None):
        self.url = url
        self.on_rate_change = on_rate_change
        self.config = None
        self.volume_db = 0.0
        self.mute = False
        self.state = {"connected": False, "state": None, "load": None, "capture_rate": None, "clipped": 0}
        self._ws = None
        self._session = None
        self._lock = asyncio.Lock()
        self._task = None

    def start(self):
        self._task = asyncio.ensure_future(self._run())

    async def close(self):
        if self._task:
            self._task.cancel()
        if self._ws is not None:
            await self._ws.close()
        if self._session is not None:
            await self._session.close()

    async def _run(self):
        self._session = aiohttp.ClientSession()
        while True:
            try:
                async with self._session.ws_connect(self.url, heartbeat=10) as ws:
                    self._ws = ws
                    self.state["connected"] = True
                    log.info("CamillaDSP connected")
                    await self._resend()
                    while True:
                        await self._poll()
                        await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                if self.state["connected"]:
                    log.warning("CamillaDSP connection lost: %s", exc)
                self.state["connected"] = False
                self._ws = None
                await asyncio.sleep(1.0)

    async def call(self, command, arg=None):
        """Send one command, return its value. Raises RuntimeError on errors."""
        if self._ws is None:
            raise RuntimeError("CamillaDSP nicht verbunden")
        async with self._lock:
            msg = command if arg is None and command.startswith("Get") else {command: arg}
            await self._ws.send_str(json.dumps(msg))
            reply = json.loads((await self._ws.receive(timeout=5)).data)
        body = reply.get(command, {})
        if body.get("result") != "Ok":
            raise RuntimeError(f"CamillaDSP {command}: {body.get('result')}")
        return body.get("value")

    async def _resend(self):
        # signal levels every 50 ms (default 1 s: the level meter would mostly get nothing)
        try:
            await self.call("SetUpdateInterval", 50)
        except RuntimeError as exc:
            log.debug("SetUpdateInterval: %s", exc)
        if self.config is not None:
            await self.call("SetConfigJson", json.dumps(self.config))
        await self.call("SetVolume", self.volume_db)
        await self.call("SetMute", self.mute)

    async def _poll(self):
        state = await self.call("GetState")
        self.state["state"] = state
        self.state["load"] = await self.call("GetProcessingLoad")
        if state in ("Inactive", "Stalled"):
            reason = await self.call("GetStopReason")
            rate = _rate_from_reason(reason)
            if rate is None and "FormatChange" in json.dumps(reason) and "Playback" not in json.dumps(reason):
                rate = int(await self.call("GetCaptureRate") or 0) or None   # CamillaDSP 4: reason without rate
            if rate and self.on_rate_change:
                self.on_rate_change(rate)

    async def set_config(self, cfg):
        self.config = cfg
        if self._ws is not None:
            await self.call("SetConfigJson", json.dumps(cfg))

    async def set_volume(self, db):
        self.mute = db is None
        if db is not None:
            self.volume_db = float(db)
        if self._ws is not None:
            await self.call("SetMute", self.mute)
            if db is not None:
                await self.call("SetVolume", self.volume_db)


def _rate_from_reason(reason):
    # e.g. {"CaptureFormatChange": 96000} or "CaptureFormatChange(96000)"
    if isinstance(reason, dict):
        for key in ("CaptureFormatChange", "CaptureRateChange"):
            if key in reason:
                return int(reason[key])
    if isinstance(reason, str):
        m = re.search(r"(?:FormatChange|RateChange)\D*(\d+)", reason)
        if m:
            return int(m[1])
    return None


# ── the world ────────────────────────────────────────────────────────────────

def detect_board():
    try:
        model = Path("/proc/device-tree/model").read_text().strip("\0 \n")
    except OSError:
        model = ""
    if "Pi 5" in model or "Compute Module 5" in model:
        return "pi5"
    if "Pi 4" in model or "Compute Module 4" in model or "Pi 400" in model:
        return "pi4"
    return "pi3b"


def detect_model():
    """HAT EEPROM product string -> Aroio model. Aroio DACs have no EEPROM; until the
    detection via I2C id exists (phase 1), the model comes from AROIO_MODEL."""
    env = os.environ.get("AROIO_MODEL")
    if env:
        return env
    return "RaspberryPi"


# ALSA sample format -> CamillaDSP 4 name
CAMILLA_FORMATS = {"S16_LE": "S16_LE", "S24_LE": "S24_4_RJ_LE", "S24_3LE": "S24_3_LE",
                   "S32_LE": "S32_LE", "FLOAT_LE": "F32_LE"}


def loopback_rate(text):
    """/proc/asound/Loopback/pcm0p/subN/hw_params -> rate, or None when closed."""
    m = re.search(r"^rate:\s*(\d+)", text, re.M)
    return int(m[1]) if m else None


def loopback_params(text):
    """hw_params -> (rate, CamillaDSP format) or None when closed."""
    rate = loopback_rate(text)
    if not rate:
        return None
    m = re.search(r"^format:\s*(\S+)", text, re.M)
    return rate, CAMILLA_FORMATS.get(m[1] if m else "", "S32_LE")


class LoopbackWatch:
    """Every player writes into the loopback (Loopback,0); CamillaDSP reads the
    other end and lets go of it when nothing plays (stop_on_inactive). Whoever
    opens the loopback next sets the rate, this watcher sees it within 0.1 s and
    restarts CamillaDSP at that rate: bit-perfect for every source, without
    trusting each player to announce its rate before it opens the device."""

    PATHS = [Path(f"/proc/asound/Loopback/pcm0p/sub{i}/hw_params") for i in range(2)]

    def __init__(self, device, interval=0.1):
        self.device = device
        self.interval = interval
        self.rate = None

    def start(self):
        asyncio.ensure_future(self._run())

    def read(self):
        for p in self.PATHS:
            try:
                params = loopback_params(p.read_text())
            except OSError:
                continue
            if params:
                return params
        return None

    def running(self):
        """True while a player actually writes (not just holds the device open, paused)."""
        for p in self.PATHS:
            try:
                if "RUNNING" in (p.parent / "status").read_text():
                    return True
            except OSError:
                continue
        return False

    def check(self, params):
        """params: (rate, format) of the player, or None when the loopback is closed."""
        if params != self.rate:
            self.rate = params
            if params:
                log.info("loopback opened at %s Hz, %s", *params)
                self.device.loopback_opened(*params)

    async def _run(self):
        stuck = 0
        while True:
            try:
                self.check(self.read())
                # a player has the loopback open but CamillaDSP stopped (e.g. after an error):
                # start it again instead of staying silent
                cam = getattr(self.device.world, "camilla", None)
                state = cam.state.get("state") if cam else None
                stuck = stuck + 1 if self.rate and state in ("Inactive", "Stalled") and self.running() else 0
                if stuck * self.interval >= 1.5:
                    log.warning("CamillaDSP %s while the loopback is open: restarting", state)
                    stuck = 0
                    cam.state["state"] = None
                    self.device.loopback_opened(*self.rate)
            except Exception:  # noqa: BLE001
                log.exception("loopback watch")
            await asyncio.sleep(self.interval)


class RealWorld:
    simulated = False
    auto_updates = True             # engine: daily check on GitHub, nightly install if wanted
    rate_from_loopback = True       # the rate is what the player opened the loopback with
    factory_filter_dir = "/usr/share/aroio/filters"
    speed = 1.0
    fmax = 1000.0
    sweep_seconds = 6.0

    def __init__(self, camilla_url=CAMILLA_URL):
        self.model = detect_model()
        self.board = detect_board()
        self.device = None
        self.camilla = CamillaClient(camilla_url)
        self.hw_volume = False
        self._cancel = False
        self._proc = None

    @property
    def dac_device(self):
        out = self.device.config.get("audio.output") if self.device else "auto"
        return resolve_output(read_cards(), out)

    def audio_outputs(self):
        return list_outputs(read_cards(), self.device.config.get("hardware.dac_driver") if self.device else None)

    def write_boot_config(self, lines):
        self._spawn(self._write_boot_file("aroio.txt", "\n".join(lines) + "\n"))

    async def _write_boot_file(self, name, text):
        mnt = "/run/aroio/boot"
        os.makedirs(mnt, exist_ok=True)
        await _run("mount", "-t", "vfat", "/dev/mmcblk0p1", mnt)
        try:
            tmp = Path(mnt) / (name + ".tmp")
            tmp.write_text(text)
            os.replace(tmp, Path(mnt) / name)
            os.sync()
        finally:
            await _run("umount", mnt)

    def attach(self, device):
        self.device = device

    def start(self):
        self.camilla.start()
        self.sources_changed(self.device.config.get("sources"))
        self.loopback = LoopbackWatch(self.device)
        self.loopback.start()
        from .inputs import InputReader
        self.inputs = InputReader(self.device)
        self.inputs.start()
        from .airplay_meta import AirplayMeta
        self.airplay = AirplayMeta(self.device)
        self.airplay.start()
        from .bt_watch import BluetoothWatch
        self.bt_watch = BluetoothWatch(self.device)
        self.bt_watch.start()
        self._spawn(self._bluetooth_start())

    async def _bluetooth_start(self):
        """Name, and pairing for 5 minutes after boot while nothing is paired yet."""
        await asyncio.sleep(5)
        cfg = self.device.config.data
        if not cfg["sources"]["bluetooth"]["enabled"]:
            await _output_ok("bluetoothctl", "power", "off")
            return
        await _output_ok("bluetoothctl", "power", "on")
        await _output_ok("bluetoothctl", "system-alias", cfg["device"]["name"])
        if not self.bt_devices:
            self.bt_pairing(300)
        self.device.publish_bluetooth()

    def publish_sim(self):
        pass

    def _spawn(self, coro):
        task = asyncio.ensure_future(coro)
        task.add_done_callback(lambda t: t.exception() and log.error("background: %s", t.exception()))
        return task

    def _rate_changed(self, rate):
        log.info("Source rate changed to %s Hz", rate)
        self.device.set_rate(rate)

    # ── CamillaDSP ──
    def camilla_apply(self, cfg):
        self._spawn(self.camilla.set_config(cfg))

    def fir_taps(self, fir_dir, preset, rate):
        files = (preset.get("fir") or {}).get(str(rate)) or {}
        path = Path(fir_dir) / files.get("L", "-")
        return path.stat().st_size // 8 if path.exists() else 0

    async def levels(self):
        if not self.camilla.state["connected"]:
            return None
        from .levels import clean
        v = await self.camilla.call("GetSignalLevelsSinceLast")
        if not v or not v.get("playback_peak"):
            return None                       # no new chunk since the last call
        return clean(v["playback_peak"], v["playback_rms"])

    def dsp_load(self, cfg, taps):
        load = self.camilla.state.get("load")
        return round(load, 1) if load is not None else None

    def set_volume(self, db):
        self._spawn(self.camilla.set_volume(db))

    # ── sources ──
    def pause_source(self, sid, user=False):
        """The previous source must let go of the loopback (all players write to
        Loopback,0,0, CamillaDSP reads its other end): pause it where the protocol
        can, otherwise end its session by restarting the player.
        user=True: pause pressed in the app; AirPlay and Bluetooth pause on the sender
        and stay connected (nothing else wants the loopback)."""
        log.info("pause %s%s", sid, " (app)" if user else "")
        self._spawn(self._pause_source(sid, user))

    async def _pause_source(self, sid, user=False):
        if sid == "bluetooth":
            await self.bt_watch.pause()                      # phone pauses (AVRCP)
            if user:
                return
            await asyncio.sleep(0.5)
            await _run("systemctl", "restart", "bluealsa-aplay.service")
        elif sid == "airplay":
            if await self.airplay.command("pause"):
                if user:
                    return
                await asyncio.sleep(0.5)
            await _run("systemctl", "restart", "shairport-sync.service")   # ends the AirPlay session
        elif sid == "spotify":
            await _run("systemctl", "restart", "aroio-spotify.service")
        elif sid == "upnp":
            await _mpd("pause 1")
        elif sid == "lms":
            await _run("systemctl", "restart", "squeezelite.service")
        elif sid == "netjack":
            # closes the way to the loopback until the computer disconnects (aroiod.netjack)
            await _run("systemctl", "kill", "--kill-whom=main", "-s", "SIGUSR1", "aroio-netjack.service")

    def resume_source(self, sid):
        log.info("resume %s", sid)
        self._spawn(self._source_command(sid, "play"))

    def source_command(self, sid, cmd):
        log.info("%s: %s", sid, cmd)
        self._spawn(self._source_command(sid, cmd))

    async def _source_command(self, sid, cmd):
        """play / next / previous on the sender (AirPlay: DACP, Bluetooth: AVRCP, UPnP: mpd)."""
        if sid == "airplay":
            ok = await self.airplay.command({"play": "play", "next": "nextitem", "previous": "previtem"}[cmd])
        elif sid == "bluetooth":
            ok = await self.bt_watch.command(cmd)
        elif sid == "upnp":
            ok = await _mpd({"play": "pause 0", "next": "next", "previous": "previous"}[cmd])
        else:
            ok = False
        if not ok:
            self.device.hub.notice(f"{cmd_text(cmd)} geht bei dieser Quelle nur am Zuspieler.", key="source_control")

    def lms_play(self, meta):
        pass

    def sources_changed(self, sources):
        """Start/stop the players to match the configuration. Runtime only (the root
        file system is read-only): the units start at boot, aroiod stops the ones
        that are switched off right after it starts."""
        for sid, unit in SOURCE_UNITS.items():
            if sid == "roon":
                continue                                   # not part of the image yet
            on = sources.get(sid, {}).get("enabled")
            self._spawn(_run("systemctl", "start" if on else "stop", unit))
        self._write_lms_env(sources.get("lms", {}))
        self._write_env("netjack.env", f"NETJACK_RATE={sources.get('netjack', {}).get('rate', 48000)}\n",
                        "aroio-netjack.service")

    def _write_env(self, name, text, unit):
        env = Path("/data/aroio") / name
        if not env.exists() or env.read_text() != text:
            env.parent.mkdir(parents=True, exist_ok=True)
            env.write_text(text)
            self._spawn(_run("systemctl", "try-restart", unit))

    def _write_lms_env(self, lms):
        """squeezelite finds the Lyrion server itself unless one is configured."""
        server = lms.get("server") or ""            # player port 3483 (config "port" is the web port)
        self._write_env("squeezelite.env", f"LMS_SERVER={'-s ' + server if server else ''}\n", "squeezelite.service")

    def rename(self, name):
        """One name everywhere: AirPlay, Spotify, UPnP (EnvironmentFile), Bluetooth (alias)."""
        env = Path("/data/aroio/names.env")
        text = "AROIO_NAME=" + json.dumps(name) + "\n"
        changed = not env.exists() or env.read_text() != text
        if changed:
            env.parent.mkdir(parents=True, exist_ok=True)
            env.write_text(text)
        self._spawn(_output_ok("bluetoothctl", "system-alias", name))
        if changed:
            self._spawn(_output_ok("systemctl", "try-restart", "shairport-sync.service", "aroio-spotify.service", "upmpdcli.service"))

    def test_noise(self, channel):
        task = getattr(self, "_noise", None)
        if task and not task.done():
            task.cancel()
        if channel:
            self._noise = asyncio.ensure_future(self._noise_loop(channel))

    async def _noise_loop(self, channel, minutes=5):
        from .sim import pink_noise
        noise = pink_noise(48000 * 4)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "noise.wav"
            write_wav(path, stereo(noise, channel), channels=2)
            t0 = time.monotonic()
            try:
                while time.monotonic() - t0 < minutes * 60:
                    proc = await asyncio.create_subprocess_exec("aplay", "-q", "-D", LOOPBACK_PLAY, str(path))
                    try:
                        await proc.wait()
                    except asyncio.CancelledError:
                        proc.terminate()
                        raise
            except asyncio.CancelledError:
                pass

    def cover(self, provider):
        if provider == "airplay" and getattr(self, "airplay", None):
            return self.airplay.cover()
        return None

    def licenses(self):
        try:
            return json.loads(Path("/usr/share/aroio/licenses.json").read_text())
        except (OSError, ValueError):
            from .sim import LICENSES
            return LICENSES

    UNITS = {"system": [], "audio": ["camilladsp", "aroiod"], "lyrion": ["squeezelite"], "airplay": ["shairport-sync", "nqptp"],
             "spotify": ["aroio-spotify"], "bluetooth": ["bluetooth", "bluealsa", "bluealsa-aplay", "aroio-bt-agent"],
             "network": ["iwd", "systemd-networkd", "aroio-hotspot", "aroio-portal-dns"]}

    def logs(self, unit):
        if unit == "kernel":
            out = subprocess.run(["dmesg"], capture_output=True, text=True, timeout=5).stdout
            return out.splitlines()[-300:]
        if unit not in self.UNITS:
            raise KeyError(unit)
        cmd = ["journalctl", "-b", "--no-pager", "-n", "300", "-o", "short"]
        for u in self.UNITS[unit]:
            cmd += ["-u", u]
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout.splitlines()

    def diagnostics_files(self):
        """Extra files for the diagnosis package (like aroio_prepare_logs in 5.1)."""
        out = {}
        for unit in self.UNITS:
            try:
                out[f"logs/{unit}.txt"] = "\n".join(self.logs(unit))
            except Exception as exc:  # noqa: BLE001
                out[f"logs/{unit}.txt"] = str(exc)
        out["logs/kernel.txt"] = "\n".join(self.logs("kernel"))
        for name, cmd in (("audio/cards.txt", ["cat", "/proc/asound/cards"]), ("audio/hw_params.txt",
                          ["aplay", "--duration=1", "-D", self.dac_device, "--dump-hw-params", "/dev/zero"]),
                          ("system/ip.txt", ["ip", "addr"]), ("system/failed.txt", ["systemctl", "--failed", "--no-pager"]),
                          ("system/boot-time.txt", ["systemd-analyze"])):
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                out[name] = r.stdout + r.stderr
            except (OSError, subprocess.SubprocessError) as exc:
                out[name] = str(exc)
        return out

    def test_tone(self, channel):
        t = np.arange(int(1.5 * 48000)) / 48000
        tone = 0.25 * np.sin(2 * np.pi * 440 * t) * np.minimum(1, np.minimum(t, t[::-1]) / 0.02)
        self._spawn(self._play(stereo(tone, channel)))

    async def _play(self, interleaved):
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            path = f.name
        write_wav(path, interleaved, channels=2)
        try:
            await _run("aplay", "-q", "-D", LOOPBACK_PLAY, path)
        finally:
            os.unlink(path)

    # ── services ──
    def spotify_status(self, secrets):
        method = "soloist" if secrets.has("spotify.soloist_key") else "librespot"
        return {"status": "ready", "method": method, "device_name": self.device.config.get("device.name")}

    def pending_login(self, provider):
        return None

    def service_login(self, provider, data, secrets):
        raise ValueError("Die Anmeldung wird mit der Lyrion-Anbindung umgesetzt (Phase 4).")

    def lyrion_status(self, cfg):
        if not cfg["sources"]["lms"]["enabled"]:
            return {"mode": "off", "server": None, "status": "off", "enabled": False}
        server = cfg["sources"]["lms"]["server"]
        port = cfg["sources"]["lms"]["port"]
        return {"mode": "external" if server else "none", "server": server or None,
                "status": "connected" if server else "not_found", "web": f"http://{server}:{port}/" if server else None}

    # ── network ──
    def network_status(self, cfg):
        addrs = _ip_addresses()
        lan = next((a for n, a in addrs.items() if n.startswith(("eth", "end", "enx"))), None)
        wifi = addrs.get("wlan0")
        if wifi == HOTSPOT_IP:
            wifi = None
        return {"lan": {"connected": bool(lan), "address": lan, "dhcp": cfg["network"]["lan"]["dhcp"], "speed": None,
                        "mac": _mac("eth0") or _mac("end0")},
                "wifi": {"connected": bool(wifi), "ssid": cfg["network"]["wifi"]["ssid"] or None, "address": wifi,
                         "signal": None, "enabled": cfg["network"]["wifi"]["enabled"], "mac": _mac(WLAN)},
                "internet": bool(lan or wifi), "hostname": cfg["network"]["hostname"]}

    def network_apply(self, net):
        log.info("network config: systemd-networkd/iwd in phase 1")

    # primitives for netsetup.NetSetup
    def links(self):
        addrs = _ip_addresses()
        lan = any(n.startswith(("eth", "end", "enx")) and _carrier(n) for n in addrs)
        wifi = bool(addrs.get(WLAN)) and addrs.get(WLAN) != HOTSPOT_IP
        return {"lan": lan, "wifi": wifi, "wlan_present": Path(f"/sys/class/net/{WLAN}").exists()}

    def id_suffix(self):
        for iface in (WLAN, "eth0", "end0"):
            try:
                mac = Path(f"/sys/class/net/{iface}/address").read_text().strip()
                return mac.replace(":", "")[-4:].upper()
            except OSError:
                continue
        return "0000"

    async def wifi_scan(self):
        if not Path(f"/sys/class/net/{WLAN}").exists():
            raise ValueError("Dieser Aroio hat kein WLAN (oder es ist ausgeschaltet).")
        await _run("ip", "link", "set", WLAN, "up")
        out = await _output("iw", "dev", WLAN, "scan")
        return parse_iw_scan(out)

    async def hotspot_start(self, ssid):
        run = Path("/run/aroio")
        run.mkdir(parents=True, exist_ok=True)
        (run / "hostapd.conf").write_text(HOSTAPD_CONF.format(iface=WLAN, ssid=ssid))
        (run / "dnsmasq.conf").write_text(DNSMASQ_CONF.format(iface=WLAN, ip=HOTSPOT_IP))
        await _run("systemctl", "stop", "iwd.service")
        await _run("ip", "link", "set", WLAN, "up")
        await _run("ip", "addr", "replace", f"{HOTSPOT_IP}/24", "dev", WLAN)
        await _run("systemctl", "start", "aroio-hotspot.service", "aroio-portal-dns.service")

    async def hotspot_stop(self):
        await _run("systemctl", "stop", "aroio-hotspot.service", "aroio-portal-dns.service")
        await _run("ip", "addr", "flush", "dev", WLAN)
        await _run("systemctl", "start", "iwd.service")

    async def wifi_join(self, ssid, psk, timeout):
        await _run("systemctl", "start", "iwd.service")
        for _ in range(20):                     # iwd needs a moment to take over the interface
            if (await _output_ok("iwctl", "station", WLAN, "show"))[0]:
                break
            await asyncio.sleep(0.5)
        await _output_ok("iwctl", "station", WLAN, "scan")
        await asyncio.sleep(3)
        cmd = ["iwctl"] + (["--passphrase", psk] if psk else []) + ["station", WLAN, "connect", ssid]
        ok, out = await _output_ok(*cmd)
        if not ok:
            if re.search(r"passphrase|Operation failed|Invalid", out, re.I):
                return False, "Das WLAN-Passwort ist falsch."
            if re.search(r"not found", out, re.I):
                return False, f"Das WLAN „{ssid}“ wurde nicht gefunden."
            return False, f"Verbindung fehlgeschlagen: {out.strip()[:120]}"
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:  # iwd's own DHCP (EnableNetworkConfiguration)
            if self.links()["wifi"]:
                return True, None
            await asyncio.sleep(0.5)
        return False, "Verbunden, aber keine IP-Adresse bekommen (Router prüfen)."

    # ── bluetooth ──
    @property
    def bt_devices(self):
        try:
            paired = subprocess.run(["bluetoothctl", "devices", "Paired"], capture_output=True, text=True, timeout=3).stdout
            connected = subprocess.run(["bluetoothctl", "devices", "Connected"], capture_output=True, text=True, timeout=3).stdout
        except (OSError, subprocess.SubprocessError):
            return []
        on = {d["address"] for d in parse_bt_devices(connected)}
        return [dict(d, connected=d["address"] in on, trusted=True) for d in parse_bt_devices(paired)]

    def bluetooth_status(self, cfg):
        until = getattr(self, "_bt_pair_until", 0)
        return {"enabled": cfg["sources"]["bluetooth"]["enabled"] and cfg["hardware"]["onboard_bluetooth"],
                "pairing": until > time.time(), "pairing_until": until or None,
                "devices": self.bt_devices, "name": cfg["device"]["name"], "codec": cfg["sources"]["bluetooth"]["codec"],
                "auto_reconnect": cfg["sources"]["bluetooth"]["auto_reconnect"]}

    def bt_pairing(self, seconds):
        """Visible and pairable for `seconds` (0 = stop). The agent (bt-agent) accepts without PIN."""
        self._bt_pair_until = time.time() + seconds if seconds else 0
        async def run():
            if seconds:
                await _output_ok("bluetoothctl", "pairable", "on")
                await _output_ok("bluetoothctl", "discoverable-timeout", str(int(seconds)))
                await _output_ok("bluetoothctl", "discoverable", "on")
            else:
                await _output_ok("bluetoothctl", "discoverable", "off")
            self.device.publish_bluetooth()
        self._spawn(run())

    def bt_remove_all(self):
        for d in self.bt_devices:
            self.bt_remove(d["address"])

    def bt_remove(self, address):
        if not re.fullmatch(r"[0-9A-F:]{17}", address):
            raise ValueError("Ungültige Adresse")
        self._spawn(_output_ok("bluetoothctl", "remove", address))

    def save_wifi(self, ssid, psk):
        """Known WLAN for iwd, written by aroiod itself (does not rely on iwd saving it)."""
        write_iwd_profile("/data/iwd", ssid, psk)

    # ── system ──
    @property
    def version(self):
        try:
            return Path("/etc/aroio-version").read_text().strip() or "dev"
        except OSError:
            return "dev"

    async def check_update(self, channel):
        """Newest fitting GitHub release (aroiod.updates), None when up to date or offline."""
        from . import updates
        repo = os.environ.get("AROIO_UPDATE_REPO", updates.REPO)
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as s:
                async with s.get(updates.API.format(repo=repo),
                                 headers={"Accept": "application/vnd.github+json",
                                          "User-Agent": "AroioOS"}) as r:
                    if r.status != 200:
                        log.warning("update check: HTTP %s", r.status)
                        return None
                    releases = await r.json()
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
            log.warning("update check: %s", exc)
            return None
        found = updates.pick_release(releases, channel, self.version)
        self._update = found
        return found

    async def install_update(self, version):
        """Download the bundle to /data (0–50 %), then `rauc install` (50–100 %).
        RAUC checks the signature against /etc/rauc/keyring.pem and writes the other slot."""
        from . import updates
        found = getattr(self, "_update", None)
        if not found or found["version"] != version:
            raise ValueError("Update nicht mehr verfügbar, bitte erneut suchen.")
        target = Path("/data/update/aroio.raucb")
        target.parent.mkdir(parents=True, exist_ok=True)
        free = os.statvfs(target.parent)
        if found["size"] and free.f_bavail * free.f_frsize < found["size"] + 50_000_000:
            raise ValueError("Zu wenig Speicherplatz für das Update.")
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3600, sock_read=60)) as s:
                async with s.get(found["url"], headers={"User-Agent": "AroioOS"}) as r:
                    if r.status != 200:
                        raise ValueError(f"Download fehlgeschlagen (HTTP {r.status}).")
                    total = int(r.headers.get("Content-Length") or found["size"] or 0)
                    done, last = 0, -1
                    with open(target, "wb") as f:
                        async for chunk in r.content.iter_chunked(1 << 16):
                            f.write(chunk)
                            done += len(chunk)
                            pct = done * 50 // total if total else 0
                            if pct != last:
                                last = pct
                                yield pct
            proc = await asyncio.create_subprocess_exec("rauc", "install", str(target),
                                                        stdout=asyncio.subprocess.PIPE,
                                                        stderr=asyncio.subprocess.STDOUT)
            tail = []
            async for raw in proc.stdout:
                line = raw.decode(errors="replace").rstrip()
                tail = (tail + [line])[-5:]
                pct = updates.rauc_progress(line)
                if pct is not None:
                    yield 50 + pct // 2
            if await proc.wait():
                log.error("rauc install: %s", " | ".join(tail))
                raise ValueError("Das Update ließ sich nicht installieren. Der Aroio läuft unverändert weiter.")
        except aiohttp.ClientError as exc:
            raise ValueError(f"Download fehlgeschlagen: {exc}") from exc
        finally:
            target.unlink(missing_ok=True)

    async def reboot(self, device):
        await asyncio.sleep(1.0)                 # let the app receive "rebooting" first
        # after an update the new slot is tried once (Pi 4/5 tryboot), see /usr/lib/aroio/rauc-tryboot
        await _run("/usr/lib/aroio/reboot")

    # ── measurement microphone ──
    def mic_status(self):
        mic = find_mic(read_cards())
        if not mic:
            return {"connected": False}
        return {"connected": True, "name": mic["name"], "serial": None, "calibration": None,
                "calibration_name": None, "card": mic["id"]}

    def stop_measurement(self):
        self._cancel = True
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()

    async def level_check(self):
        """Pink noise in steps of 3 dB until the microphone sees about −30 dBFS."""
        from .sim import pink_noise
        mic = find_mic(read_cards())
        if not mic:
            raise ValueError("Kein Messmikrofon gefunden.")
        noise = pink_noise(48000 * 1)
        gain, level = -50.0, -120.0
        while gain <= -6:
            if self._cancel:
                self._cancel = False
                raise ValueError("abgebrochen")
            rec = await self._play_record(stereo(noise * 10 ** (gain / 20), "both"), mic, seconds=1.2)
            level = 20 * np.log10(max(np.sqrt(np.mean(rec[len(rec) // 3:] ** 2)), 1e-9))
            yield min(0.95, (gain + 50) / 44), None
            if level > -30:
                break
            gain += 3
        self.level_gain_db = gain
        status = "ok" if -45 < level < -8 else ("low" if level <= -45 else "high")
        text = {"ok": "Passt.", "low": "Das Mikrofon hört zu wenig. Lautsprecher und Verstärker an?",
                "high": "Zu laut für das Mikrofon. Bitte am Verstärker leiser stellen."}[status]
        yield 1.0, {"spl": round(level, 1), "unit": "dBFS", "status": status, "text": text}

    async def measure(self, sweep, channel, position, progress=None):
        mic = find_mic(read_cards())
        if not mic:
            raise ValueError("Kein Messmikrofon gefunden.")
        gain = getattr(self, "level_gain_db", -20.0) + 6
        seconds = len(sweep) / 48000 + 1.5
        task = asyncio.ensure_future(self._play_record(stereo(sweep * 10 ** (gain / 20), channel), mic, seconds))
        t0 = time.monotonic()
        while not task.done():
            if progress:
                progress(min(0.95, (time.monotonic() - t0) / seconds))
            await asyncio.sleep(0.25)
        return task.result()

    async def _play_record(self, interleaved, mic, seconds):
        """Record the microphone while playing through CamillaDSP. The caller (wizard)
        has paused the music; the active preset is the bypass during measurements (phase 1)."""
        with tempfile.TemporaryDirectory() as tmp:
            play, rec = Path(tmp) / "play.wav", Path(tmp) / "rec.wav"
            write_wav(play, interleaved, channels=2)
            self._proc = await asyncio.create_subprocess_exec(
                "arecord", "-q", "-D", f"hw:CARD={mic['id']},DEV=0", "-f", "S32_LE", "-r", "48000", "-c", "1",
                "-d", str(int(np.ceil(seconds + 0.5))), str(rec))
            await asyncio.sleep(0.3)
            await _run("aplay", "-q", "-D", LOOPBACK_PLAY, str(play))
            await self._proc.wait()
            return read_wav(rec)


WLAN = "wlan0"
HOTSPOT_IP = "192.168.4.1"

HOSTAPD_CONF = """# written by aroiod: setup hotspot (open, only while nothing else is configured)
interface={iface}
driver=nl80211
ssid={ssid}
country_code=DE
hw_mode=g
channel=6
ieee80211n=1
wmm_enabled=1
auth_algs=1
ignore_broadcast_ssid=0
"""

DNSMASQ_CONF = """# written by aroiod: DHCP for the setup hotspot, every name resolves to the Aroio (captive portal)
interface={iface}
bind-interfaces
listen-address={ip}
no-resolv
no-hosts
address=/#/{ip}
dhcp-range=192.168.4.10,192.168.4.100,255.255.255.0,10m
dhcp-option=3,{ip}
dhcp-option=6,{ip}
dhcp-option=114,http://{ip}/einrichtung
dhcp-authoritative
"""


def parse_iw_scan(text):
    """`iw dev wlan0 scan` -> [{"ssid", "signal", "secure"}], strongest per SSID, hidden ones dropped."""
    nets, cur = {}, None
    for line in text.splitlines():
        if line.startswith("BSS "):
            if cur and cur.get("ssid"):
                old = nets.get(cur["ssid"])
                if not old or cur["signal"] > old["signal"]:
                    nets[cur["ssid"]] = cur
            cur = {"ssid": None, "signal": -100, "secure": False}
            continue
        if cur is None:
            continue
        s = line.strip()
        if s.startswith("signal:"):
            cur["signal"] = round(float(s.split()[1]))
        elif s.startswith("SSID:"):
            name = s[5:].strip()
            cur["ssid"] = name if name and "\\x00" not in name else None
        elif s.startswith(("RSN:", "WPA:")) or s.startswith("capability:") and "Privacy" in s:
            cur["secure"] = True
    if cur and cur.get("ssid"):
        old = nets.get(cur["ssid"])
        if not old or cur["signal"] > old["signal"]:
            nets[cur["ssid"]] = cur
    return sorted(nets.values(), key=lambda n: -n["signal"])


def _mac(iface):
    try:
        return Path(f"/sys/class/net/{iface}/address").read_text().strip()
    except OSError:
        return None


def _carrier(iface):
    try:
        return Path(f"/sys/class/net/{iface}/carrier").read_text().strip() == "1"
    except OSError:
        return False


async def _output(*cmd):
    ok, out = await _output_ok(*cmd)
    if not ok:
        raise RuntimeError(f"{' '.join(cmd)}: {out.strip()}")
    return out


async def _output_ok(*cmd):
    try:
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    except OSError as exc:
        return False, str(exc)
    out, _ = await proc.communicate()
    text = re.sub(r"\x1b\[[0-9;]*m", "", out.decode(errors="replace"))   # iwctl colours
    return proc.returncode == 0, text


def _ip_addresses():
    """IPv4 address per interface. `ip -j` (iproute2), falling back to parsing plain
    `ip -4 -o addr` output (works with BusyBox too)."""
    try:
        out = subprocess.run(["ip", "-j", "-4", "addr"], capture_output=True, text=True, timeout=2).stdout
        return {i["ifname"]: a["local"] for i in json.loads(out) for a in i.get("addr_info", [])
                if i["ifname"] != "lo"}
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    try:
        out = subprocess.run(["ip", "-4", "-o", "addr"], capture_output=True, text=True, timeout=2).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    return parse_ip_addr(out)


def parse_ip_addr(text):
    """`ip -4 -o addr` (iproute2) or `ip -4 addr` (BusyBox) -> {ifname: address}"""
    out, iface = {}, None
    for line in text.splitlines():
        m = re.match(r"^\d+:\s+([^:@\s]+)", line)
        if m:
            iface = m[1]
        m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", line)
        if m and iface and iface != "lo" and iface not in out:
            out[iface] = m[1]
    return out


async def _mpd(command):
    """One command to the local MPD (UPnP renderer behind upmpdcli)."""
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", 6600), 2)
        await reader.readline()
        writer.write(command.encode() + b"\n")
        await writer.drain()
        reply = await asyncio.wait_for(reader.readline(), 2)
        writer.close()
        return reply.startswith(b"OK")
    except (OSError, asyncio.TimeoutError) as exc:
        log.debug("mpd %s: %s", command, exc)
        return False


def cmd_text(cmd):
    return {"play": "Weiterspielen", "next": "Weiterschalten", "previous": "Zurückschalten"}.get(cmd, cmd)


async def _run(*cmd):
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL,
                                                stderr=asyncio.subprocess.PIPE)
    _, err = await proc.communicate()
    if proc.returncode:
        raise RuntimeError(f"{' '.join(cmd)}: {err.decode(errors='replace').strip()}")
