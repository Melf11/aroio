"""The simulated world: everything outside aroiod, for development without a Pi.

Implements the same interface the real world (phase 1) will: CamillaDSP,
sources, Lyrion, Spotify, network, Bluetooth, updates, microphone. On top it
offers `event()` for the simulator page: rotate the encoder, press keys, start
AirPlay from a phone, plug in the microphone, lose the network ...
"""

import asyncio
import copy
import logging
import random
import time

import numpy as np

from . import roomcorr as rc
from .library import art_url

log = logging.getLogger("aroiod.sim")

EXTERNAL = {
    "airplay": {"who": "iPhone von Anna", "title": "Hafenlichter", "artist": "Elbe Quartett",
                "album": "Nachtfahrt", "duration": 245, "format": {"codec": "ALAC", "bits": 16, "rate": 44100}},
    "spotify": {"who": "Spotify auf Pixel 8", "title": "Weite Felder", "artist": "Mira Kollektiv",
                "album": "Sommerwege", "duration": 212, "format": {"codec": "FLAC", "bits": 24, "rate": 44100}},
    "bluetooth": {"who": "Galaxy S24", "title": "Bluetooth-Audio", "artist": "Galaxy S24", "album": "",
                  "duration": 0, "format": {"codec": "LDAC", "bits": 24, "rate": 96000}},
    "upnp": {"who": "BubbleUPnP", "title": "Sinfonie Nr. 3 – II. Adagio", "artist": "Kupfer Sinfonietta",
             "album": "Live in Hamburg", "duration": 611, "format": {"codec": "FLAC", "bits": 24, "rate": 192000}},
    "roon": {"who": "Roon Core", "title": "Blue in Green", "artist": "Atlas Trio", "album": "Spuren",
             "duration": 338, "format": {"codec": "FLAC", "bits": 24, "rate": 96000}},
    "input": {"who": "Eingang", "title": "Eingang", "artist": "Analog / Digital", "album": "", "duration": 0,
              "format": {"codec": "PCM", "bits": 24, "rate": 96000}},
}

NETWORKS = [("Zuhause", -48, True), ("Zuhause-5G", -55, True), ("FRITZ!Box 7590 XY", -67, True),
            ("Nachbar", -78, True), ("Gast", -71, False)]


def pink_noise(n, seed=0):
    """1/f noise, RMS about −15 dBFS (used for level checks on the device)."""
    rng = np.random.default_rng(seed)
    spec = np.fft.rfft(rng.normal(size=n))
    f = np.arange(len(spec))
    f[0] = 1
    noise = np.fft.irfft(spec / np.sqrt(f), n)
    return noise / np.sqrt(np.mean(noise ** 2)) * 10 ** (-15 / 20)


class MeasurementCancelled(Exception):
    pass


class SimWorld:
    simulated = True
    hw_volume = False
    speed = 1.0
    fmax = 1000.0

    def __init__(self, model="AroioLT", board="pi4", fast=False, mic_mode="none"):
        self.model, self.board = model, board
        self.device = None
        self.camilla = None
        self.camilla_loads = 0
        self.sweep_seconds = 1.0 if fast else 4.0
        self.fast = fast
        # microphone: none | sim (virtual room) | host (real mic in the simulator browser)
        self.mic_mode = mic_mode
        self.host_mic = None          # label reported by the simulator browser
        self.request = None           # last audio request for the simulator browser
        self._pending = {}            # request id -> Future (host measurements)
        self._signals = {}            # request id -> float32 bytes (signal to play)
        self._seq = 0
        self.host_gain_db = -20.0     # playback level for host measurements (from level check)
        self.host_timeout = None      # tests: override the wait for the simulator page
        self.noise_next = False
        self.too_loud_next = False
        self.internet = True
        self.lan = True
        self.wifi_ssid = None
        self.lyrion_external = "192.168.1.10"
        self.spotify_needs_key = False
        self.logins = {}
        self.bt_devices = [{"address": "A4:C3:F0:11:22:33", "name": "Galaxy S24", "connected": False, "trusted": True}]
        self.bt_pair_until = 0
        self.update_version = "0.2.0"
        self.leds = {"network": "on", "status": "on"}
        self.booting = False
        self.events = []
        self.room = rc.SimRoom(48000)
        self._cancel = False
        self.volume_db = None
        self.tone = None
        self.usb_dac = False

    def attach(self, device):
        self.device = device
        self.active_driver = device.config.get("hardware.dac_driver")   # takes effect at boot

    # ── sound cards (as /proc/asound/cards would list them) ──
    def cards(self):
        driver = getattr(self, "active_driver", "auto")
        cards = [{"index": 0, "id": "Loopback", "driver": "Loopback", "name": "Loopback"},
                 {"index": 1, "id": "vc4hdmi0", "driver": "vc4-hdmi", "name": "vc4-hdmi-0"}]
        if driver == "onboard":
            if self.board != "pi5":
                cards.append({"index": 2, "id": "Headphones", "driver": "bcm2835_headpho", "name": "bcm2835 Headphones"})
        elif self.model.startswith("Aroio") or driver == "aroio":
            cards.append({"index": 2, "id": "AroioDAC", "driver": "HifiberryDacp", "name": "Aroio DAC"})
        else:
            cards.append({"index": 2, "id": "IQaudIODAC", "driver": "IQaudIODAC", "name": "Raspberry Pi DAC+"})
        if self.usb_dac:
            cards.append({"index": 3, "id": "DragonFly", "driver": "USB-Audio", "name": "AudioQuest DragonFly Red"})
        if self.mic_mode == "sim":
            cards.append({"index": 4, "id": "U18dB", "driver": "USB-Audio", "name": "Umik-1  Gain: 18dB"})
        return cards

    @property
    def dac_device(self):
        from .real import resolve_output
        return resolve_output(self.cards(), self.device.config.get("audio.output") if self.device else "auto")

    def audio_outputs(self):
        from .real import list_outputs
        return list_outputs(self.cards())

    def set_dac_driver(self, driver):
        from .models import dac_driver_lines
        self.log("Boot-Partition aroio.txt: " + " | ".join(dac_driver_lines(driver)[1:] or ["(leer)"]) + ", aktiv nach Neustart")

    def log(self, text):
        self.events.insert(0, {"t": time.strftime("%H:%M:%S"), "text": text})
        del self.events[40:]
        self.publish_sim()

    def publish_sim(self):
        if not self.device:
            return
        d = self.device
        p = d.hub.topics.get("player", {})
        track = p.get("track") or {}
        net = self.network_status(d.config.data)
        ip = (net["lan"].get("address") if net["lan"]["connected"] else net["wifi"].get("address")) or "–"
        lines = [d.config.get("device.name"), f"IP {ip}"]
        if p.get("state") == "playing":
            lines += [f"▶ {track.get('title', '')}", track.get("artist", "")]
        else:
            lines += ["Bereit", f"{d.config.get('network.hostname')}.local"]
        if self.booting:
            lines = ["AroioOS", "startet …", "", ""]
        self.leds["network"] = "on" if (self.lan or self.wifi_ssid) else ("blink" if not d.config.get("setup.completed") else "off")
        d.hub.publish("sim", {
            "model": self.model, "board": self.board, "mic": self.mic_mode != "none", "mic_mode": self.mic_mode,
            "host_mic": self.host_mic, "internet": self.internet,
            "lan": self.lan, "wifi": self.wifi_ssid, "lyrion_external": self.lyrion_external,
            "spotify_needs_key": self.spotify_needs_key, "noise_next": self.noise_next, "usb_dac": self.usb_dac,
            "leds": self.leds, "display": lines, "booting": self.booting, "events": self.events,
            "camilla": {"loads": self.camilla_loads, "pipeline": [s.get("names") or s.get("name") for s in (self.camilla or {}).get("pipeline", [])],
                        "samplerate": (self.camilla or {}).get("devices", {}).get("samplerate"),
                        "capture_samplerate": (self.camilla or {}).get("devices", {}).get("capture_samplerate")},
            "volume_db": self.volume_db, "tone": self.tone, "clients": d.hub.clients,
            "fixed_level": d.fixed_level,
            "camilla_config": self.camilla, "request": self.request,
            "room": {"highpass": 38.0, "modes": [list(m) for m in rc.SimRoom.MODES], "right_gain_db": -0.63},
            "external": list(EXTERNAL),
        })

    # ── CamillaDSP ──
    def camilla_apply(self, cfg):
        self.camilla = copy.deepcopy(cfg)
        self.camilla_loads += 1
        d = cfg["devices"]
        self.log(f"CamillaDSP: {d['samplerate']} Hz"
                 + (f" (Quelle {d['capture_samplerate']} Hz, umgerechnet)" if "capture_samplerate" in d else "")
                 + f", {len(cfg['pipeline'])} Stufen")

    def fir_taps(self, fir_dir, preset, rate):
        files = (preset.get("fir") or {}).get(str(rate)) or {}
        path = fir_dir / files.get("L", "-")
        return path.stat().st_size // 8 if path.exists() else 0

    def dsp_load(self, cfg, taps):
        cores = {"pi3b": 1.0, "pi4": 2.2, "pi5": 4.5}[self.board]
        rate = cfg["devices"]["samplerate"]
        base = 1.5 + 0.4 * sum(len(s.get("names", [])) for s in cfg["pipeline"])
        fir = taps * rate / 48000 / 65536 * 18 if taps else 0
        return round(min(100.0, (base + fir) / cores), 1)

    # ── sources ──
    def pause_source(self, sid):
        self.log(f"{sid}: angehalten")

    def resume_source(self, sid):
        self.log(f"{sid}: weiter")

    def source_command(self, sid, cmd):
        self.log(f"{sid}: {cmd}")
        if sid in EXTERNAL and EXTERNAL[sid]["duration"]:
            meta = self._external_meta(sid, nr=random.randint(2, 9))
            self.device.external_meta(sid, meta)

    def lms_play(self, meta):
        self.log(f"Lyrion: spielt „{meta['title']}“")

    def sources_changed(self, sources):
        self.log("Quellen: " + ", ".join(k for k, v in sources.items() if v["enabled"]))

    def set_volume(self, db):
        self.volume_db = db
        self.publish_sim()

    def test_tone(self, channel):
        self.tone = {"channel": channel, "at": time.time()}
        self._audio_request("tone", channel=channel, seconds=1.5)
        self.log(f"Testton {'links' if channel == 'L' else 'rechts' if channel == 'R' else 'beide'}")

    def rename(self, name):
        self.log(f"Name überall gesetzt: {name} (AirPlay, Spotify, UPnP, Bluetooth, Lyrion)")

    def _external_meta(self, sid, nr=1):
        e = EXTERNAL[sid]
        title = e["title"] if nr == 1 else f"{e['title']} ({nr})"
        return {"id": f"{sid}:{nr}", "title": title, "artist": e["artist"], "album": e["album"],
                "duration": e["duration"], "image": art_url(f"{sid}:{e['album'] or e['artist']}"),
                "format": dict(e["format"]), "provider": sid, "controller": e["who"],
                "live": e["duration"] == 0}

    # ── services ──
    def spotify_status(self, secrets):
        if self.spotify_needs_key and not secrets.has("spotify.soloist_key"):
            return {"status": "needs_key", "method": "soloist", "device_name": self.device.config.get("device.name")}
        method = "soloist" if secrets.has("spotify.soloist_key") else "librespot"
        return {"status": "ready", "method": method, "device_name": self.device.config.get("device.name"),
                "key_expires": secrets.get("spotify.key_expires")}

    def pending_login(self, provider):
        login = self.logins.get(provider)
        if login and login["expires"] > time.time():
            return {k: login[k] for k in ("code", "url", "expires")}
        return None

    def service_login(self, provider, data, secrets):
        if provider == "tidal":
            if data.get("action") == "start":
                code = "".join(random.choice("ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(5))
                self.logins["tidal"] = {"code": code, "url": "link.tidal.com", "expires": time.time() + 300}
                self.log(f"TIDAL: Gerätecode {code}")
                return {"code": code, "url": "link.tidal.com", "expires": self.logins["tidal"]["expires"]}
            if data.get("action") == "confirm_sim":
                self.logins.pop("tidal", None)
                secrets.set("tidal.token", "sim-token")
                secrets.set("tidal.account", "anna@example.org")
                self.log("TIDAL: angemeldet")
                return {"ok": True}
        if provider == "qobuz":
            email, password = data.get("email", ""), data.get("password", "")
            if "@" not in email or len(password) < 4:
                raise ValueError("E-Mail oder Passwort ist falsch.")
            secrets.set("qobuz.token", "sim-token")
            secrets.set("qobuz.account", email)
            self.log("Qobuz: angemeldet")
            return {"ok": True}
        if provider == "spotify":
            key = (data.get("soloist_key") or "").strip()
            if len(key) < 16:
                raise ValueError("Der Schlüssel ist zu kurz. Bitte vollständig kopieren.")
            secrets.set("spotify.soloist_key", key)
            secrets.set("spotify.key_expires", time.strftime("%Y-%m-%d", time.localtime(time.time() + 90 * 86400)))
            self.log("Spotify: Soloist-Schlüssel gespeichert")
            return {"ok": True}
        raise ValueError("Unbekannter Dienst")

    def lyrion_status(self, cfg):
        configured = cfg["sources"]["lms"]["server"]
        mode = cfg["services"]["lyrion_local"]
        if mode == "on" or (mode == "auto" and not (configured or self.lyrion_external)):
            return {"mode": "local", "server": "dieser Aroio", "status": "connected", "version": "9.1.0",
                    "plugins": ["TIDAL", "Qobuz", "Radio"]}
        server = configured or self.lyrion_external
        if not server:
            return {"mode": "none", "server": None, "status": "not_found"}
        return {"mode": "external", "server": server, "status": "connected", "version": "9.0.3",
                "found_automatically": not configured, "plugins": ["TIDAL", "Qobuz", "Radio"]}

    # ── network ──
    def network_status(self, cfg):
        lan_cfg, wifi_cfg = cfg["network"]["lan"], cfg["network"]["wifi"]
        lan_addr = (lan_cfg["address"] if not lan_cfg["dhcp"] else "192.168.1.57") if self.lan else None
        wifi_addr = "192.168.1.88" if self.wifi_ssid else None
        hotspot = not self.lan and not self.wifi_ssid and cfg["network"]["hotspot"] == "auto"
        return {"lan": {"connected": self.lan, "address": lan_addr, "dhcp": lan_cfg["dhcp"], "speed": "1 Gbit/s" if self.lan else None},
                "wifi": {"connected": bool(self.wifi_ssid), "ssid": self.wifi_ssid or wifi_cfg["ssid"] or None,
                         "address": wifi_addr, "signal": -55 if self.wifi_ssid else None,
                         "enabled": wifi_cfg["enabled"] and cfg["hardware"]["onboard_wifi"]},
                "hotspot": {"active": hotspot, "ssid": "Aroio-Einrichtung" if hotspot else None},
                "internet": self.internet and (self.lan or bool(self.wifi_ssid)),
                "hostname": cfg["network"]["hostname"]}

    def network_apply(self, net):
        self.log(f"Netzwerk angewendet: {net['hostname']}.local, LAN {'DHCP' if net['lan']['dhcp'] else net['lan']['address']}")
        if net["wifi"]["ssid"] and not self.wifi_ssid and net["wifi"]["enabled"]:
            self.wifi_ssid = net["wifi"]["ssid"]

    async def wifi_scan(self):
        await asyncio.sleep(0.2 if self.fast else 1.2)
        return [{"ssid": s, "signal": sig + random.randint(-3, 3), "secure": sec} for s, sig, sec in NETWORKS]

    async def wifi_connect(self, ssid, psk):
        await asyncio.sleep(0.2 if self.fast else 1.5)
        if psk and len(psk) < 8:
            raise ValueError("Das WLAN-Passwort ist falsch.")
        self.wifi_ssid = ssid
        self.log(f"WLAN verbunden: {ssid}")

    # ── bluetooth ──
    def bluetooth_status(self, cfg):
        return {"enabled": cfg["sources"]["bluetooth"]["enabled"] and cfg["hardware"]["onboard_bluetooth"],
                "pairing": self.bt_pair_until > time.time(), "pairing_until": self.bt_pair_until or None,
                "devices": self.bt_devices, "name": cfg["device"]["name"],
                "codec": cfg["sources"]["bluetooth"]["codec"],
                "auto_reconnect": cfg["sources"]["bluetooth"]["auto_reconnect"]}

    def bt_pairing(self, seconds):
        self.bt_pair_until = time.time() + seconds if seconds else 0
        self.log("Bluetooth: Kopplung offen" if seconds else "Bluetooth: Kopplung beendet")

    def bt_remove(self, address):
        self.bt_devices = [d for d in self.bt_devices if d["address"] != address]

    # ── updates ──
    async def check_update(self, channel):
        await asyncio.sleep(0.2 if self.fast else 1.2)
        if not self.internet or not self.update_version:
            return None
        notes = ["Raumkorrektur: genauere Messung bei sehr kleinen Räumen",
                 "Lyrion: Albumansicht lädt schneller", "Fehlerbehebungen"]
        if channel == "beta":
            notes.insert(0, "Beta: neue Klangcharaktere")
        return {"version": self.update_version + ("-beta.1" if channel == "beta" else ""), "notes": notes}

    async def install_update(self, version):
        steps = 10
        for i in range(1, steps + 1):
            await asyncio.sleep(0.05 if self.fast else 0.6)
            yield i * 100 // steps
        self.log(f"Update {version} in Partition B geschrieben, aktiv nach Neustart")
        self._installed = version

    async def reboot(self, device):
        self.booting = True
        self.publish_sim()
        device.hub.publish("system", {"rebooting": True})
        await asyncio.sleep(0.2 if self.fast else 3.0)
        self.active_driver = device.config.get("hardware.dac_driver")
        if getattr(self, "_installed", None):
            from . import engine
            engine.VERSION = self._installed
            device.update.update(current=self._installed, available=None, state="idle", progress=0, notes=[])
            self._installed = None
            self.update_version = None
        self.booting = False
        device.stop()
        device.hub.publish("system", {"rebooting": False, "booted_at": time.time()})
        device.publish_all()
        self.log("Neustart abgeschlossen")

    # ── microphone + room ──
    def mic_status(self):
        if self.mic_mode == "host":
            if not self.host_mic:
                return {"connected": False}
            return {"connected": True, "name": self.host_mic + " (am Rechner)", "serial": "–",
                    "calibration": None, "calibration_name": None, "host": True}
        if self.mic_mode != "sim":
            return {"connected": False}
        return {"connected": True, "name": "miniDSP UMIK-1 (simuliert)", "serial": "700-4512",
                "calibration": [(f, 0.0) for f in (10, 20, 100, 1000, 10000, 20000)] if self.internet else None,
                "calibration_name": "700-4512 (automatisch geladen)" if self.internet else None}

    async def level_check(self):
        if self.mic_mode == "host":
            yield 0.1, None
            res = await self._host_request("level", timeout=20, seconds=4.0)
            rms = float(res.get("rms_dbfs", -120))
            self.host_gain_db = float(res.get("gain_db", self.host_gain_db))
            if rms < -55:
                yield 1.0, {"spl": rms, "status": "low", "unit": "dBFS",
                            "text": "Das Mikrofon hört fast nichts. Lautsprecher an? Richtiges Mikrofon gewählt?"}
            elif rms > -8:
                yield 1.0, {"spl": rms, "status": "high", "unit": "dBFS",
                            "text": "Zu laut für das Mikrofon. Bitte am Rechner leiser stellen."}
            else:
                yield 1.0, {"spl": rms, "status": "ok", "unit": "dBFS", "text": "Passt."}
            return
        self._audio_request("noise", seconds=2.5)
        for i in range(1, 11):
            if self._cancel:
                self._cancel = False
                raise MeasurementCancelled("abgebrochen")
            await asyncio.sleep(0.05 if self.fast else 0.25)
            yield i / 10, None
        spl = 76.0 if not self.too_loud_next else 92.0
        self.too_loud_next = False
        yield 1.0, {"spl": spl, "status": "ok" if spl < 85 else "high",
                    "text": "Passt." if spl < 85 else "Zu laut, bitte am Verstärker leiser stellen."}

    async def measure(self, sweep, channel, position, progress=None):
        self.log(f"Messung Position {position + 1}, {'links' if channel == 'L' else 'rechts'}"
                 + (" (echtes Mikrofon am Rechner)" if self.mic_mode == "host" else ""))
        if self.mic_mode == "host":
            seconds = len(sweep) / 48000
            task = asyncio.ensure_future(self._host_request(
                "measure", timeout=seconds + 20, signal=sweep, channel=channel, seconds=seconds,
                record_seconds=seconds + 1.5, gain_db=self.host_gain_db))
            t0 = time.monotonic()
            while not task.done():
                if self._cancel:
                    self._cancel = False
                    task.cancel()
                    raise MeasurementCancelled("abgebrochen")
                if progress:
                    progress(min(0.95, (time.monotonic() - t0) / (seconds + 2)))
                await asyncio.sleep(0.25)
            data = task.result()
            return np.frombuffer(data, dtype="<f4").astype(np.float64)
        self._audio_request("play", signal=sweep, channel=channel)
        total = 0.3 if self.fast else self.sweep_seconds
        for i in range(1, 6):
            if self._cancel:
                self._cancel = False
                raise MeasurementCancelled("abgebrochen")
            await asyncio.sleep(total / 5)
            if progress:
                progress(i / 5)
        noise = (-20.0 - 10 * np.log10(self.sweep_seconds)) if self.noise_next else -75.0
        self.noise_next = False
        rec = await asyncio.get_event_loop().run_in_executor(
            None, lambda: self.room.record(sweep, channel, position, noise_db=noise))
        self.publish_sim()
        return rec

    def stop_measurement(self):
        self._cancel = True
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()

    # ── simulator browser: audio on the host ──
    def _audio_request(self, kind, signal=None, **params):
        """Ask the simulator page to play something (fire and forget)."""
        self._seq += 1
        rid = f"r{self._seq}"
        if signal is not None:
            self._signals = {rid: np.asarray(signal, dtype="<f4").tobytes()}
        self.request = dict(params, id=rid, kind=kind, has_signal=signal is not None, at=time.time())
        self.publish_sim()
        return rid

    async def _host_request(self, kind, timeout, signal=None, **params):
        """Ask the simulator page to play and/or record, wait for its result."""
        rid = self._audio_request(kind, signal=signal, **params)
        fut = asyncio.get_event_loop().create_future()
        self._pending[rid] = fut
        try:
            return await asyncio.wait_for(fut, self.host_timeout or timeout)
        except asyncio.TimeoutError:
            raise ValueError("Der Simulator hat nicht geantwortet. Ist dort „Ton am Rechner“ eingeschaltet "
                             "und das Mikrofon freigegeben?") from None
        finally:
            self._pending.pop(rid, None)

    def signal(self, rid):
        return self._signals.get(rid)

    def resolve(self, rid, payload):
        fut = self._pending.get(rid)
        if not fut or fut.done():
            raise KeyError(rid)
        if isinstance(payload, dict) and payload.get("error"):
            fut.set_exception(ValueError(payload["error"]))
        else:
            fut.set_result(payload)

    # ── simulator events ──
    async def event(self, name, data):
        d = self.device
        if name == "encoder":
            d.on_encoder(int(data.get("steps", 1)))
        elif name == "key":
            if not d.on_key(data["key"]):
                raise ValueError("Unbekannte Taste")
            self.log(f"Taste {data['key']}")
        elif name == "external_start":
            sid = data["source"]
            meta = self._external_meta(sid)
            if not d.source_started(sid, meta, rate=meta["format"]["rate"]):
                d.hub.notice(f"{sid} ist ausgeschaltet und wurde ignoriert.", key="source_off")
            elif sid == "bluetooth":
                for dev in self.bt_devices:
                    dev["connected"] = True
                d.publish_bluetooth()
            self.log(f"{EXTERNAL[sid]['who']} startet {sid}")
        elif name == "external_stop":
            d.source_stopped(data["source"])
            if data["source"] == "bluetooth":
                for dev in self.bt_devices:
                    dev["connected"] = False
                d.publish_bluetooth()
        elif name == "track_end":
            if d.meta and d.meta.get("duration"):
                d.seek(d.meta["duration"] - 3)
        elif name == "model":
            self.model = data["model"]
            d.publish_device()
            d.publish_player()
            d.publish_sources()
        elif name == "board":
            self.board = data["board"]
            d.publish_device()
            d.apply_dsp()
        elif name == "mic":
            self.mic_mode = "sim" if data["on"] else "none"
            if d.wizard:
                d.wizard.publish()
            self.log("UMIK-1 (simuliert) eingesteckt" if data["on"] else "Mikrofon abgezogen")
        elif name == "mic_mode":
            if data["mode"] not in ("none", "sim", "host"):
                raise ValueError("Unbekannter Mikrofon-Modus")
            self.mic_mode = data["mode"]
            if "label" in data:
                self.host_mic = data["label"] or None
            if d.wizard:
                d.wizard.publish()
            self.log({"none": "Kein Mikrofon", "sim": "Mikrofon: simulierter Raum",
                      "host": f"Mikrofon am Rechner: {self.host_mic or 'nicht gewählt'}"}[self.mic_mode])
        elif name == "usb_dac":
            self.usb_dac = bool(data["on"])
            self.log("USB-DAC eingesteckt" if self.usb_dac else "USB-DAC abgezogen")
            d.apply_dsp()
        elif name == "noise_next":
            self.noise_next = True
            self.log("Nächste Messung mit Störgeräusch")
        elif name == "lan":
            self.lan = bool(data["on"])
            d.publish_network()
        elif name == "wifi_drop":
            self.wifi_ssid = None
            d.publish_network()
        elif name == "internet":
            self.internet = bool(data["on"])
            d.publish_network()
        elif name == "lyrion_external":
            self.lyrion_external = data.get("server") or None
            d.publish_services()
        elif name == "spotify_needs_key":
            self.spotify_needs_key = bool(data["on"])
            d.publish_services()
        elif name == "tidal_confirm":
            d.service_login("tidal", {"action": "confirm_sim"})
            d.publish_services()
        elif name == "bt_phone_pairs":
            if self.bt_pair_until < time.time():
                raise ValueError("Bluetooth-Kopplung ist nicht offen.")
            self.bt_devices.append({"address": "F0:%02X:11:22:33:44" % random.randint(0, 255),
                                    "name": random.choice(["iPhone von Ben", "Pixel 9", "MacBook"]),
                                    "connected": False, "trusted": True})
            self.bt_pair_until = 0
            d.publish_bluetooth()
            d.hub.notice("Neues Gerät gekoppelt.", key="bt")
        elif name == "update_available":
            self.update_version = data.get("version", "0.2.0")
        elif name == "old_device":
            from .migration import SAMPLE_FILTERS, SAMPLE_USERCONFIG
            text = data.get("userconfig") or SAMPLE_USERCONFIG
            files = {f: _fake_fir(f) for f in SAMPLE_FILTERS}
            d.offer_migration(text, files, source="aroio-ng (simuliert)")
            self.log("Altgerät erkannt: userconfig.txt + Filter")
        elif name == "first_boot":
            d.factory_reset()
            self.lan = data.get("lan", False)
            self.wifi_ssid = None
            d.publish_network()
            self.log("Erststart simuliert (Werkseinstellungen)")
        else:
            raise ValueError(f"Unbekanntes Ereignis {name}")
        self.publish_sim()


def _fake_fir(name):
    rng = np.random.default_rng(abs(hash(name)) % 2 ** 32)
    taps = np.zeros(4096)
    taps[128] = 0.8
    taps[129:700] = rng.normal(0, 0.002, 571) * np.exp(-np.arange(571) / 120)
    return taps.astype("<f8").tobytes()
