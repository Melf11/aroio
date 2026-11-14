"""The real world on a Raspberry Pi: CamillaDSP, ALSA, systemd, network.

Same interface as aroiod.sim.SimWorld. Phase 1 status:
- done:     CamillaDSP control (config, volume, mute, load, rate changes), DAC and
            measurement microphone detection, test tone, room measurement with
            aplay/arecord, network status, board detection, reboot
- minimal:  sources (systemd units on/off, events from player hooks via
            /api/v1/internal/source), Spotify/Lyrion/Bluetooth status
- missing:  pausing other sources through their own interfaces, BlueZ/iwd D-Bus,
            RAUC updates, TIDAL/Qobuz login (Lyrion plugins)
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
LOOPBACK_PLAY = "hw:Loopback,0,0"      # players and aroiod's own signals write here
SOURCE_UNITS = {"lms": "squeezelite.service", "spotify": "aroio-spotify.service",
                "airplay": "shairport-sync.service", "upnp": "upmpdcli.service",
                "bluetooth": "bluealsa-aplay.service", "roon": "roonbridge.service"}


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


def list_outputs(cards):
    """Every card that can play music: no loopback, no measurement microphone."""
    out = []
    for c in cards:
        if c["id"] == "Loopback" or find_mic([c]):
            continue
        out.append({"id": f"hw:CARD={c['id']},DEV=0", "name": c["name"], "card": c["id"], "kind": output_kind(c)})
    order = {"hat": 0, "usb": 1, "analog": 2, "hdmi": 3}
    return sorted(out, key=lambda o: (order[o["kind"]], o["card"]))


def resolve_output(cards, preferred):
    """The configured output if it is present, else the automatic choice."""
    if preferred and preferred != "auto" and any(o["id"] == preferred for o in list_outputs(cards)):
        return preferred
    return find_dac(cards)


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


class RealWorld:
    simulated = False
    speed = 1.0
    fmax = 1000.0
    sweep_seconds = 6.0

    def __init__(self, camilla_url=CAMILLA_URL):
        self.model = detect_model()
        self.board = detect_board()
        self.device = None
        self.camilla = CamillaClient(camilla_url, on_rate_change=self._rate_changed)
        self.hw_volume = False
        self._cancel = False
        self._proc = None

    @property
    def dac_device(self):
        out = self.device.config.get("audio.output") if self.device else "auto"
        return resolve_output(read_cards(), out)

    def audio_outputs(self):
        return list_outputs(read_cards())

    def set_dac_driver(self, driver):
        from .models import dac_driver_lines
        self._spawn(self._write_boot_file("aroio.txt", "\n".join(dac_driver_lines(driver)) + "\n"))

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

    def dsp_load(self, cfg, taps):
        load = self.camilla.state.get("load")
        return round(load, 1) if load is not None else None

    def set_volume(self, db):
        self._spawn(self.camilla.set_volume(db))

    # ── sources ──
    def pause_source(self, sid):
        log.info("pause %s (source control: phase 1)", sid)

    def resume_source(self, sid):
        log.info("resume %s (source control: phase 1)", sid)

    def source_command(self, sid, cmd):
        log.info("%s: %s (source control: phase 1)", sid, cmd)

    def lms_play(self, meta):
        pass

    def sources_changed(self, sources):
        for sid, unit in SOURCE_UNITS.items():
            on = sources.get(sid, {}).get("enabled")
            self._spawn(_run("systemctl", "enable" if on else "disable", "--now", unit))

    def rename(self, name):
        log.info("rename to %s: service configs follow in phase 1", name)

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
        server = cfg["sources"]["lms"]["server"]
        return {"mode": "external" if server else "none", "server": server or None,
                "status": "connected" if server else "not_found"}

    # ── network ──
    def network_status(self, cfg):
        addrs = _ip_addresses()
        lan = next((a for n, a in addrs.items() if n.startswith(("eth", "end", "enx"))), None)
        wifi = addrs.get("wlan0")
        if wifi == HOTSPOT_IP:
            wifi = None
        return {"lan": {"connected": bool(lan), "address": lan, "dhcp": cfg["network"]["lan"]["dhcp"], "speed": None},
                "wifi": {"connected": bool(wifi), "ssid": cfg["network"]["wifi"]["ssid"] or None, "address": wifi,
                         "signal": None, "enabled": cfg["network"]["wifi"]["enabled"]},
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
    def bluetooth_status(self, cfg):
        return {"enabled": cfg["sources"]["bluetooth"]["enabled"], "pairing": False, "pairing_until": None,
                "devices": [], "name": cfg["device"]["name"], "codec": cfg["sources"]["bluetooth"]["codec"],
                "auto_reconnect": cfg["sources"]["bluetooth"]["auto_reconnect"]}

    def bt_pairing(self, seconds):
        raise ValueError("Bluetooth-Kopplung folgt in Phase 1 (BlueZ).")

    def bt_remove(self, address):
        raise ValueError("Bluetooth folgt in Phase 1 (BlueZ).")

    # ── system ──
    async def check_update(self, channel):
        return None

    async def install_update(self, version):
        raise ValueError("Updates über RAUC folgen in Phase 1.")
        yield 0  # pragma: no cover

    async def reboot(self, device):
        await _run("systemctl", "reboot")

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
    try:
        out = subprocess.run(["ip", "-j", "-4", "addr"], capture_output=True, text=True, timeout=2).stdout
        return {i["ifname"]: a["local"] for i in json.loads(out) for a in i.get("addr_info", [])
                if i["ifname"] != "lo"}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}


async def _run(*cmd):
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL,
                                                stderr=asyncio.subprocess.PIPE)
    _, err = await proc.communicate()
    if proc.returncode:
        raise RuntimeError(f"{' '.join(cmd)}: {err.decode(errors='replace').strip()}")
