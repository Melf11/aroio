"""The device: playback, source switching, volume, sample rate, DSP, services.

All decisions live here and are the same on the real device and in the
simulator. Everything that touches hardware or other programs goes through
`self.world` (aroiod.sim.SimWorld in the simulator; the real world with
CamillaDSP, Lyrion, BlueZ, iwd, RAUC follows in phase 1).

Exactly one source plays at a time. When a new source starts, the previous one
is paused through its own control interface: no mixer, so no forced sample
rate and no resampling.
"""

import asyncio
import logging
import math
import time
import uuid
from pathlib import Path

from . import dsp, models, proxy
from .config import RATES, Config, Invalid
from .library import PROVIDERS, SimLibrary
from .store import Secrets, atomic_write_bytes

log = logging.getLogger("aroiod.engine")

VERSION = "0.1.0-dev"

SOURCES = {
    "lms": {"name": "Aroio-App & Lyrion", "short": "Musik", "controls": True},
    "spotify": {"name": "Spotify", "short": "Spotify", "controls": True},
    "airplay": {"name": "AirPlay", "short": "AirPlay", "controls": True},
    "upnp": {"name": "UPnP / DLNA", "short": "UPnP", "controls": True},
    "bluetooth": {"name": "Bluetooth", "short": "Bluetooth", "controls": True},
    "input": {"name": "Eingang", "short": "Eingang", "controls": False},
    "roon": {"name": "Roon", "short": "Roon", "controls": True},
    "netjack": {"name": "NetJack", "short": "NetJack", "controls": False},
}

# What the Aroio can do with a playing source (the world may know better, see
# World.source_controls): only these buttons appear in the player.
TRANSPORT = {"play", "pause", "next", "previous"}
LMS_CONTROLS = TRANSPORT | {"seek", "shuffle", "queue"}


def volume_db(percent):
    """0..100 % -> dB. Steeper at the bottom like an analogue pot."""
    if percent <= 0:
        return None  # mute
    return round(-60.0 * (1 - percent / 100) ** 1.6, 1)


INTERNET_TEST_URL = "https://api.github.com/zen"


class Device:
    def __init__(self, data_dir, world, hub):
        self.data = Path(data_dir)
        self.data.mkdir(parents=True, exist_ok=True)
        (self.data / "filters").mkdir(exist_ok=True)
        (self.data / "measurements").mkdir(exist_ok=True)
        self.world = world
        self.hub = hub
        self.config = Config(self.data / "config.json")
        self.secrets = Secrets(self.data / "secrets" / "secrets.json")
        self.library = SimLibrary(services_logged_in=self._logged_in)
        # everything in "Musik" comes through Lyrion (own music, radio, TIDAL/Qobuz plugins)
        self.library.lyrion_on = lambda: self.config.get("sources.lms.enabled", True)
        self.library.enabled = lambda p: self.library.lyrion_on() and (
            p in ("local", "radio", "favorites") or self.config.get(f"services.{p}.enabled", False))
        self.queue, self.index = [], -1
        self.state = "stopped"
        self.source = None
        self.meta = None            # current track meta
        self.pos_base, self.started_at = 0.0, None
        self.shuffle, self.repeat = False, "off"
        self.volume = self.config.get("audio.start_volume")
        self.muted = False
        self.compare_bypass = False
        self.rate = 48000
        self.capture_format = "S32_LE"
        self.source_meta = {}       # last meta per outside source (may arrive before "start")
        self.dsp_status = {}
        self._end_task = None
        self.update = {"current": getattr(world, "version", None) or VERSION, "available": None, "state": "idle", "progress": 0,
                       "notes": [], "checked": None}
        self.pending_migration = None
        self.reboot_required = False
        self.wizard = None          # set by app (wizard.RoomWizard)
        self.netsetup = None        # set by app (netsetup.NetSetup)
        self.levels = None          # set by app (levels.Levels)
        self.measuring = False      # room measurement: correction off, Cleaner kept, 0 dB
        self._ir_learn = None       # Future while teaching a remote key
        self.last_ir = None
        self.factory_dir = self._factory_filters()
        self._ensure_factory_presets()
        from .auth import Auth
        self.auth = Auth(self)

    # ── helpers ──────────────────────────────────────────────────────────────
    @property
    def model_id(self):
        chosen = self.config.get("hardware.model")
        return chosen if chosen in models.MODELS else self.world.model

    @property
    def model(self):
        return models.MODELS[self.model_id]

    @property
    def fixed_level(self):
        return self.model["fixed_level"]

    def _logged_in(self, provider):
        if provider == "local":
            return True
        return self.secrets.has(f"{provider}.token")

    def position(self):
        if self.state == "playing" and self.started_at is not None:
            return self.pos_base + (time.monotonic() - self.started_at)
        return self.pos_base

    def start(self):
        if self.netsetup:
            self.netsetup.start()
        self.world.set_volume(0.0 if self.fixed_level else volume_db(self.volume))
        self.world.rename(self.config.get("device.name"))
        self.publish_all()
        self.apply_dsp()
        if getattr(self.world, "auto_updates", False):
            self._update_task = asyncio.ensure_future(self._update_loop())

    async def _update_loop(self, first_delay=300, interval=600, check_every=86400):
        """Look for updates once a day; with update.auto install them at night while nothing plays."""
        from .updates import auto_install_due
        await asyncio.sleep(first_delay)
        last_check = 0.0
        while True:
            try:
                if time.time() - last_check > check_every:
                    last_check = time.time()
                    await self.check_update()
                if (self.update["available"] and self.update["state"] == "idle"
                        and auto_install_due(time.localtime().tm_hour, self.state == "playing",
                                             self.config.get("update.auto"), self.update["current"])):
                    await self.install_update()
                    await self.reboot()
            except Exception as exc:          # never let the loop die
                log.warning("automatic update: %s", exc)
                self.update.update(state="idle", progress=0)
                self.publish_update()
            await asyncio.sleep(interval)

    def publish_all(self):
        self.publish_device()
        self.publish_player()
        self.publish_queue()
        self.publish_sources()
        self.publish_dsp()
        self.publish_services()
        self.publish_network()
        self.publish_bluetooth()
        self.publish_update()
        self.publish_migration()

    # ── publishing ───────────────────────────────────────────────────────────
    def publish_device(self):
        c = self.config.data
        board = models.BOARDS[self.world.board]
        self.hub.publish("device", {
            "name": c["device"]["name"], "hostname": c["network"]["hostname"],
            "language": c["device"]["language"], "theme": c["device"]["theme"],
            "expert_mode": c["device"]["expert_mode"],
            "model": self.model_id, "model_label": self.model["label"],
            "model_detected": self.world.model,
            "models": [{"id": k, "label": m["label"]} for k, m in models.MODELS.items()],
            "board": self.world.board, "board_label": board["label"],
            "fixed_level": self.fixed_level, "has_input": self.model["has_input"] or c["sources"]["input"]["enabled"],
            "version": self.update["current"], "setup_completed": c["setup"]["completed"],
            "reboot_required": self.reboot_required,
            "sound_card_missing": self.sound_card_missing(),
            "simulated": self.world.simulated,
        })

    def publish_player(self):
        sig = self.signal_info()
        self.hub.publish("player", {
            "state": self.state, "source": self.source,
            "source_name": SOURCES[self.source]["name"] if self.source else None,
            "track": self.meta, "position": round(self.position(), 2),
            "position_at": time.time(), "shuffle": self.shuffle, "repeat": self.repeat,
            "volume": None if self.fixed_level else self.volume,
            "volume_db": None if self.fixed_level else volume_db(0 if self.muted else self.volume),
            "volume_limit": self.config.get("audio.volume_limit"),
            "muted": self.muted,
            "can": self.can(),
            "signal": sig,
        })

    def controls(self):
        """The set of things the current source lets the Aroio do (play, pause, stop, next,
        previous, seek, shuffle, queue)."""
        if self.source in (None, "lms"):
            return LMS_CONTROLS
        return set(self.world.source_controls(self.source))

    def can(self):
        c = self.controls()
        out = {k: k in c for k in ("play", "pause", "stop", "next", "previous", "shuffle", "queue")}
        out["seek"] = "seek" in c and bool(self.meta and self.meta.get("duration"))
        return out

    def publish_queue(self):
        items = []
        for i, tid in enumerate(self.queue):
            m = self.library.track_meta(tid)
            items.append({"id": tid, "title": m["title"], "subtitle": m["artist"], "image": m["image"],
                          "duration": m["duration"], "index": i})
        self.hub.publish("queue", {"items": items, "index": self.index})

    def publish_sources(self):
        c = self.config.data["sources"]
        out = []
        for sid, s in SOURCES.items():
            if sid == "input" and not self.model["has_input"] and not c["input"]["enabled"]:
                continue
            out.append({"id": sid, "name": s["name"], "short": s["short"], "enabled": c[sid]["enabled"],
                        "active": self.source == sid, "playing": self.source == sid and self.state == "playing"})
        self.hub.publish("sources", out)

    def publish_dsp(self):
        d = self.config.data["dsp"]
        presets = []
        for p in d["presets"]:
            item = {k: p[k] for k in ("id", "name", "kind", "origin", "gain_db", "source") if k in p}
            if p["kind"] == "fir":
                item["rates"] = sorted(int(r) for r in p.get("fir", {}))
            if p["kind"] == "peq":
                item["filters"] = sum(len(v) for v in p.get("peq", {}).values())
            item["created"] = p.get("created")
            presets.append(item)
        self.hub.publish("dsp", {"enabled": d["enabled"], "active_preset": d["active_preset"],
                                 "ms_cleaner": d["ms_cleaner"], "character": d["character"],
                                 "compare_bypass": self.compare_bypass, "presets": presets,
                                 "status": self.dsp_status})

    def publish_services(self):
        c = self.config.data
        sp = self.world.spotify_status(self.secrets)
        self.hub.publish("services", {
            "spotify": dict(sp, enabled=c["sources"]["spotify"]["enabled"]),
            "tidal": {"enabled": c["services"]["tidal"]["enabled"], "logged_in": self._logged_in("tidal"),
                      "account": self.secrets.get("tidal.account"), "login": self.world.pending_login("tidal")},
            "qobuz": {"enabled": c["services"]["qobuz"]["enabled"], "logged_in": self._logged_in("qobuz"),
                      "account": self.secrets.get("qobuz.account")},
            "lyrion": dict(self.world.lyrion_status(c), protected=self.secrets.has("lms.user"),
                           user=self.secrets.get("lms.user")),
            "airplay": {"enabled": c["sources"]["airplay"]["enabled"]},
            "upnp": {"enabled": c["sources"]["upnp"]["enabled"]},
            "roon": {"enabled": c["sources"]["roon"]["enabled"]},
            "netjack": dict(c["sources"]["netjack"]),
        })

    def proxy_url(self):
        """The proxy with credentials, '' without one (never sent to the app)."""
        p = self.config.data["network"]["proxy"]
        return proxy.compose(p["url"], p["user"], self.secrets.get("proxy.password", ""))

    def set_proxy(self, text):
        url, user, password = proxy.parse(text)
        before, stored = self.proxy_url(), dict(self.config.data["network"]["proxy"])
        self.secrets.set("proxy.password", password)
        self.patch_config({"network": {"proxy": {"url": url, "user": user}}})   # applies a new address
        if stored == {"url": url, "user": user} and self.proxy_url() != before:  # only the password
            self.world.proxy_apply(self.proxy_url())
        self.publish_network()

    async def internet_test(self):
        """Reach the internet the way updates and downloads do (through the proxy, if set)."""
        await self.world.fetch(INTERNET_TEST_URL, max_bytes=4096)

    def publish_network(self, only_changed=False):
        status = self.world.network_status(self.config.data)
        p = self.config.data["network"]["proxy"]
        status["proxy"] = {"set": bool(p["url"]),
                           "display": proxy.display(p["url"], p["user"], self.secrets.has("proxy.password"))}
        if self.netsetup:
            status.update(self.netsetup.status())
        if only_changed and status == getattr(self, "_network_published", None):
            return
        self._network_published = status
        self.hub.publish("network", status)

    def publish_bluetooth(self):
        self.hub.publish("bluetooth", self.world.bluetooth_status(self.config.data))

    def publish_update(self):
        self.hub.publish("update", dict(self.update, channel=self.config.get("update.channel"),
                                        auto=self.config.get("update.auto")))

    def publish_migration(self):
        m = self.pending_migration
        self.hub.publish("migration", {"pending": bool(m), "report": m["report"] if m else [],
                                       "source": m["source"] if m else None,
                                       "state": m["state"] if m else None})

    # ── signal path ──────────────────────────────────────────────────────────
    def active_preset(self):
        d = self.config.data["dsp"]
        if not d["enabled"] or self.compare_bypass or self.measuring:
            return dsp_bypass()
        return self.selected_preset()

    def selected_preset(self):
        d = self.config.data["dsp"]
        return next((p for p in d["presets"] if p["id"] == d["active_preset"]), dsp_bypass())

    def apply_dsp(self):
        """(Re)build the CamillaDSP config for the current rate and preset."""
        c = self.config.data
        rate_in = self.rate
        preset = self.active_preset()
        # A/B comparison: "without correction" at the rate and the loudness of the preset
        # being compared, so only the sound differs
        compared = self.selected_preset() if (self.compare_bypass and c["dsp"]["enabled"]
                                              and not self.measuring) else None
        if compared and compared["kind"] == "bypass":
            compared = None
        fixed = c["audio"]["rate_mode"] == "fixed"
        rate_out = c["audio"]["fixed_rate"] if fixed else rate_in
        note = None
        max_rate = c["audio"]["max_rate"]
        if rate_out > max_rate:
            # highest rate the DAC takes, same family if possible (44.1k / 48k multiples)
            allowed = [r for r in sorted(RATES) if r <= max_rate]
            family = [r for r in allowed if (r % 44100 == 0) == (rate_out % 44100 == 0)] or allowed
            rate_out = max(family)
            note = "max_rate"
        basis = compared or preset
        fir_dir = self.preset_dir(basis)
        if basis["kind"] == "fir":
            have = sorted(int(r) for r in basis.get("fir", {}))
            if rate_out not in have:
                # nearest available rate, prefer same family (44.1k / 48k multiples)
                family = [r for r in have if (r % 44100 == 0) == (rate_out % 44100 == 0)] or have
                rate_out = min(family, key=lambda r: abs(r - rate_out))
                note = "missing_rate"
        if compared:
            try:
                match = min(0.0, dsp.loudness_db(compared, rate_out, fir_dir))
            except (OSError, ValueError) as exc:
                log.warning("loudness of %s: %s", compared["id"], exc)
                match = float(compared.get("gain_db", 0.0))
            preset = dict(preset, gain_db=match)
        try:
            cfg = dsp.camilla_config(
                preset, rate_out, ms_cleaner=c["dsp"]["ms_cleaner"] and c["dsp"]["enabled"],
                fir_dir=str(fir_dir), playback=self.world.dac_device,
                capture_rate=rate_in if rate_in != rate_out else None, resampler=c["audio"]["resampler"],
                chunksize=c["audio"]["chunksize"] or None, target_level=c["audio"]["target_level"] or None,
                release_capture=self.world.rate_from_loopback, capture_format=self.capture_format)
        except dsp.MissingRate:
            cfg = dsp.camilla_config(dsp_bypass(), rate_in, playback=self.world.dac_device)
            note = "error"
        self.world.camilla_apply(cfg)
        taps = 0
        if preset["kind"] == "fir":
            taps = self.world.fir_taps(fir_dir, preset, rate_out)
        limit = models.fir_limit(self.world.board, rate_out)
        self.dsp_status = {"rate_in": rate_in, "rate_out": rate_out, "resampled": rate_in != rate_out,
                           "pipeline_empty": dsp.is_bit_perfect(cfg),
                           "processing": bool(cfg["pipeline"]), "note": note,
                           "preset": preset["name"], "fir_taps": taps,
                           "compare_gain_db": preset["gain_db"] if compared else None,
                           "too_heavy": bool(taps and taps > limit), "fir_limit": limit,
                           "load": self.world.dsp_load(cfg, taps), "measuring": self.measuring,
                           "recordings": (self.data / "measurements" / "last" / "info.txt").exists()}
        self.publish_dsp()
        self.publish_player()
        return cfg

    def audio_hardware(self):
        from .models import DAC_DRIVERS
        return {"outputs": self.world.audio_outputs(), "selected": self.config.get("audio.output"),
                "active": self.world.dac_device, "driver": self.config.get("hardware.dac_driver"),
                "drivers": [{k: d[k] for k in ("id", "label", "hint")} for d in DAC_DRIVERS],
                "reboot_required": self.reboot_required}

    def signal_info(self):
        fmt = (self.meta or {}).get("format") or {}
        bit_perfect = bool(self.dsp_status.get("pipeline_empty")) and not self.muted and (
            self.fixed_level or self.volume >= 100 or self.world.hw_volume) and fmt.get("codec") not in ("MP3", "AAC", "OGG")
        return dict(self.dsp_status, codec=fmt.get("codec"), bits=fmt.get("bits"), bit_perfect=bit_perfect,
                    source_rate=fmt.get("rate"), cleaner=self.config.get("dsp.ms_cleaner"))

    def loopback_opened(self, rate, fmt="S32_LE"):
        """A player opened the loopback at this rate and sample format (device):
        CamillaDSP stopped when the previous one closed it and starts again with
        exactly these parameters."""
        self.rate = 176400 if int(rate) > 192000 else int(rate)
        self.capture_format = fmt
        self.apply_dsp()

    def remote_volume(self, percent):
        """Volume from the sending device (iPhone over AirPlay, phone over Bluetooth)."""
        if self.fixed_level:
            return
        self.set_volume(value=max(0, min(int(round(percent)), self.config.get("audio.volume_limit", 100))))

    def set_rate(self, rate):
        rate = int(rate)
        if rate > 192000:          # DSD: converted to PCM before the DSP
            rate = 176400
        if rate != self.rate:
            self.rate = rate
            self.apply_dsp()

    # ── sources ──────────────────────────────────────────────────────────────
    def source_started(self, sid, meta=None, rate=None):
        """A source starts playing (from the app, or from outside: AirPlay,
        Spotify Connect, a phone over Bluetooth ...). The previous source is paused."""
        if not self.config.get(f"sources.{sid}.enabled", True):
            log.info("Ignoring disabled source %s", sid)
            return False
        prev = self.source
        if prev and prev != sid:
            if prev == "lms":
                self._freeze()
            self.world.pause_source(prev)
            self.hub.notice(f"{SOURCES[sid]['name']} spielt jetzt, {SOURCES[prev]['name']} wurde angehalten.",
                            key="source_switch")
        self.source = sid
        if sid != "lms":
            self._cancel_end()
            self.meta = meta
            self.pos_base, self.started_at = 0.0, time.monotonic()
            self.state = "playing"
        if rate and not self.world.rate_from_loopback:
            self.set_rate(rate)
        self.publish_player()
        self.publish_sources()
        return True

    def source_stopped(self, sid):
        if self.source == sid:
            self._freeze()
            self.state = "stopped" if sid in ("bluetooth", "input", "airplay", "netjack", "spotify") else "paused"
            self.publish_player()
            self.publish_sources()

    def source_paused(self, sid):
        """The sender paused (iPhone, phone): show it, the session stays."""
        if self.source == sid and self.state == "playing":
            self._freeze()
            self.state = "paused"
            self.publish_player()
            self.publish_sources()

    def source_resumed(self, sid):
        if self.source == sid and self.state != "playing":
            self.state = "playing"
            self.started_at = time.monotonic()
            self.publish_player()
            self.publish_sources()

    def external_meta(self, sid, meta):
        self.source_meta[sid] = meta
        if self.source == sid:
            meta = dict(meta)
            self.meta = meta
            pos = meta.pop("position", None) or 0.0
            self.pos_base, self.started_at = pos, time.monotonic() if self.state == "playing" else None
            if meta.get("format", {}).get("rate") and not self.world.rate_from_loopback:
                self.set_rate(meta["format"]["rate"])
            self.publish_player()

    # ── transport (app, encoder, buttons, IR) ────────────────────────────────
    def play_items(self, item_id, mode="play", start=0):
        tracks = self.library.resolve(item_id)
        if not tracks:
            raise KeyError(item_id)
        self.library.remember(item_id)
        if mode == "play" or not self.queue:
            start = max(0, min(int(start or 0), len(tracks) - 1))
            self.queue, self.index = list(tracks), start
            self._start_track(start)
        elif mode == "next":
            self.queue[self.index + 1:self.index + 1] = tracks
            self.hub.notice(f"{len(tracks)} Titel kommen als Nächstes.", key="queue")
        else:
            self.queue += tracks
            self.hub.notice(f"{len(tracks)} Titel zur Warteschlange hinzugefügt.", key="queue")
        self.publish_queue()

    def _start_track(self, index, position=0.0):
        if not (0 <= index < len(self.queue)):
            self.stop()
            return
        self.source_started("lms")
        self.index = index
        self.meta = self.library.track_meta(self.queue[index])
        self.pos_base, self.started_at = position, time.monotonic()
        self.state = "playing"
        self.set_rate(self.meta["format"]["rate"])
        self._schedule_end()
        self.world.lms_play(self.meta)
        self.publish_player()
        self.publish_queue()
        self.publish_sources()

    def _schedule_end(self):
        self._cancel_end()
        dur = (self.meta or {}).get("duration") or 0
        if dur and self.state == "playing":
            remaining = max(0.05, dur - self.position())
            loop = asyncio.get_event_loop()
            self._end_task = loop.call_later(remaining / self.world.speed, self._track_ended)

    def _cancel_end(self):
        if self._end_task:
            self._end_task.cancel()
            self._end_task = None

    def _track_ended(self):
        self._end_task = None
        if self.repeat == "one":
            self._start_track(self.index)
        elif self.index + 1 < len(self.queue):
            self._start_track(self.index + 1)
        elif self.repeat == "all" and self.queue:
            self._start_track(0)
        else:
            self.stop()

    def _freeze(self):
        self.pos_base = self.position()
        self.started_at = None
        self._cancel_end()

    def play(self):
        if self.state == "playing":
            return
        if self.source in (None, "lms"):
            if not self.queue:
                return
            if self.state == "stopped":
                self._start_track(max(self.index, 0))
                return
            self.source_started("lms")
        elif "play" not in self.controls():
            return                                  # only the sender can start it again
        else:
            self.world.resume_source(self.source)
        self.state = "playing"
        self.started_at = time.monotonic()
        self._schedule_end()
        self.publish_player()
        self.publish_sources()

    def pause(self):
        if self.state != "playing":
            return
        if self.source != "lms" and "pause" not in self.controls():
            if "stop" in self.controls():
                self.stop()                         # the only way to silence it: end the session
            return
        self._freeze()
        self.state = "paused"
        if self.source != "lms":
            self.world.pause_source(self.source, user=True)   # keep the session (AirPlay, Bluetooth)
        self.publish_player()
        self.publish_sources()

    def toggle(self):
        self.pause() if self.state == "playing" else self.play()

    def stop(self):
        if self.source not in (None, "lms") and self.state == "playing":
            self.world.pause_source(self.source)    # ends the session of the sender
        self._freeze()
        self.pos_base = 0.0
        self.state = "stopped"
        self.publish_player()
        self.publish_sources()

    def next(self):
        if self.source == "lms":
            if self.index + 1 < len(self.queue):
                self._start_track(self.index + 1)
            elif self.repeat == "all" and self.queue:
                self._start_track(0)
        elif self.source and "next" in self.controls():
            self.world.source_command(self.source, "next")

    def previous(self):
        if self.source == "lms":
            if self.position() > 3 or self.index == 0:
                self.seek(0)
            else:
                self._start_track(self.index - 1)
        elif self.source and "previous" in self.controls():
            self.world.source_command(self.source, "previous")

    def seek(self, seconds):
        if self.source not in (None, "lms"):
            if "seek" not in self.controls():
                return
            self.world.source_command(self.source, "seek", float(seconds))
        dur = (self.meta or {}).get("duration") or 0
        self.pos_base = max(0.0, min(float(seconds), max(0.0, dur - 0.5)))
        if self.state == "playing":
            self.started_at = time.monotonic()
            self._schedule_end()
        self.publish_player()

    def set_shuffle(self, on):
        self.shuffle = bool(on)
        if self.shuffle and self.source == "lms" and len(self.queue) > self.index + 2:
            import random
            rest = self.queue[self.index + 1:]
            random.shuffle(rest)
            self.queue = self.queue[:self.index + 1] + rest
            self.publish_queue()
        self.publish_player()

    def set_repeat(self, mode):
        if mode not in ("off", "all", "one"):
            raise ValueError(mode)
        self.repeat = mode
        self.publish_player()

    def queue_jump(self, index):
        self._start_track(int(index))

    def queue_remove(self, index):
        index = int(index)
        if not (0 <= index < len(self.queue)):
            raise IndexError(index)
        if index == self.index:
            raise ValueError("Der laufende Titel kann nicht entfernt werden.")
        del self.queue[index]
        if index < self.index:
            self.index -= 1
        self.publish_queue()

    def queue_move(self, src, dst):
        src, dst = int(src), int(dst)
        if not (0 <= src < len(self.queue) and 0 <= dst < len(self.queue)):
            raise IndexError(src)
        item = self.queue.pop(src)
        self.queue.insert(dst, item)
        if self.index == src:
            self.index = dst
        elif src < self.index <= dst:
            self.index -= 1
        elif dst <= self.index < src:
            self.index += 1
        self.publish_queue()

    def queue_clear(self):
        keep = self.queue[self.index] if 0 <= self.index < len(self.queue) and self.state != "stopped" else None
        self.queue, self.index = ([keep], 0) if keep else ([], -1)
        self.publish_queue()

    # ── volume ───────────────────────────────────────────────────────────────
    def set_volume(self, value=None, delta=None):
        if self.fixed_level:
            raise ValueError("Dieses Modell hat einen festen Ausgangspegel. Die Lautstärke stellst du am Verstärker.")
        limit = self.config.get("audio.volume_limit")
        v = self.volume + delta if delta is not None else value
        self.volume = int(max(0, min(limit, round(v))))
        self.muted = False
        self.world.set_volume(volume_db(self.volume))
        self.publish_player()

    def set_mute(self, on):
        self.muted = bool(on)
        self.world.set_volume(None if self.muted else volume_db(self.volume))
        self.publish_player()

    # ── hardware input ───────────────────────────────────────────────────────
    def on_encoder(self, steps):
        if not self.fixed_level:
            self.set_volume(delta=steps * self.config.get("hardware.encoder_step"))

    def on_key(self, key):
        """Buttons on the device and IR remote (same key names as rc-core)."""
        actions = {"play_pause": self.toggle, "KEY_PLAYPAUSE": self.toggle, "KEY_PLAY": self.play,
                   "KEY_PAUSE": self.pause, "KEY_STOP": self.stop, "KEY_NEXT": self.next,
                   "KEY_PREVIOUS": self.previous, "KEY_MUTE": lambda: self.set_mute(not self.muted),
                   "KEY_VOLUMEUP": lambda: self.on_encoder(1), "KEY_VOLUMEDOWN": lambda: self.on_encoder(-1)}
        for n in range(1, 10):
            actions[f"KEY_{n}"] = (lambda i=n: self.select_preset_by_number(i))
        fn = actions.get(key)
        if fn:
            fn()
            return True
        return False

    def select_preset_by_number(self, n):
        presets = self.config.data["dsp"]["presets"]
        if 0 < n <= len(presets):
            self.patch_config({"dsp": {"active_preset": presets[n - 1]["id"]}})
            self.hub.notice(f"Klang: {presets[n - 1]['name']}", key="preset")

    # ── config ───────────────────────────────────────────────────────────────
    def patch_config(self, patch):
        before = self.config.data
        after = self.config.patch(patch)
        changed = {k for k in after if after.get(k) != before.get(k)}
        if "dsp" in changed or "audio" in changed:
            self.apply_dsp()
        if "sources" in changed:
            for sid in SOURCES:
                if not after["sources"][sid]["enabled"] and self.source == sid:
                    self.source_stopped(sid)
                    self.source = None
            self.world.sources_changed(after["sources"])
            self.publish_sources()
            self.publish_services()
        if "services" in changed:
            self.publish_services()
        if "network" in changed:
            self.world.network_apply(after["network"])
            if after["network"]["proxy"] != before["network"]["proxy"]:
                self.world.proxy_apply(self.proxy_url())
            self.publish_network()
        # aroio.txt only when its lines change (e.g. model "auto" -> "RaspberryPi" does not)
        if "hardware" in changed and self._boot_lines(before["hardware"]) != self._boot_lines(after["hardware"]):
            self.write_boot_config()
            self.reboot_required = True
        if "hardware" in changed or "device" in changed or "setup" in changed:
            self.publish_device()
        if "update" in changed:
            self.publish_update()
        if "device" in changed and after["device"]["name"] != before["device"]["name"]:
            self.world.rename(after["device"]["name"])
            self.publish_services()
        if changed & {"sources", "hardware", "device"}:
            self.publish_bluetooth()
        return after

    # ── DSP presets ──────────────────────────────────────────────────────────
    def save_preset(self, preset, activate=True):
        presets = [p for p in self.config.data["dsp"]["presets"] if p["id"] != preset["id"]]
        presets.append(preset)
        patch = {"dsp": {"presets": presets}}
        if activate:
            patch["dsp"]["active_preset"] = preset["id"]
        self.patch_config(patch)

    def delete_preset(self, pid):
        if pid == "bypass" or pid.startswith("werk-"):
            raise ValueError("Fest eingebaute Klangeinstellungen können nicht gelöscht werden.")
        presets = self.config.data["dsp"]["presets"]
        target = next((p for p in presets if p["id"] == pid), None)
        if not target:
            raise KeyError(pid)
        patch = {"dsp": {"presets": [p for p in presets if p["id"] != pid]}}
        if self.config.get("dsp.active_preset") == pid:
            patch["dsp"]["active_preset"] = "bypass"
        self.patch_config(patch)
        if target.get("measurement"):
            (self.data / "measurements" / f"{target['measurement']}.json").unlink(missing_ok=True)
        for files in (target.get("fir") or {}).values():
            for f in files.values():
                (self.data / "filters" / f).unlink(missing_ok=True)

    def rename_preset(self, pid, name):
        presets = [dict(p, name=name) if p["id"] == pid else p for p in self.config.data["dsp"]["presets"]]
        self.patch_config({"dsp": {"presets": presets}})

    def create_eq(self, name=None):
        """Own equalizer without a measurement: three neutral bands to start with
        (bass shelf, mids, treble shelf), active at once so every change is audible."""
        names = {p["name"] for p in self.config.data["dsp"]["presets"]}
        if not name:
            name, n = "Eigener Equalizer", 2
            while name in names:
                name, n = f"Eigener Equalizer {n}", n + 1
        bands = [{"type": "lowshelf", "freq": 100.0, "gain": 0.0, "q": 0.7},
                 {"type": "peaking", "freq": 1000.0, "gain": 0.0, "q": 1.0},
                 {"type": "highshelf", "freq": 8000.0, "gain": 0.0, "q": 0.7}]
        preset = {"id": "eq-" + uuid.uuid4().hex[:8], "name": name[:40], "kind": "peq", "origin": "user",
                  "peq": {"L": [dict(b) for b in bands], "R": [dict(b) for b in bands]},
                  "created": time.strftime("%Y-%m-%d")}
        self.save_preset(preset, activate=True)
        self.patch_config({"dsp": {"enabled": True}})
        return preset

    # ── headphone correction (aroiod.headphones) ─────────────────────────────
    async def headphone_list(self):
        """Models of the headphone filter project, cached for an hour."""
        import json
        from . import headphones
        cached = getattr(self, "_headphones", None)
        if cached and time.monotonic() - cached[0] < 3600:
            return cached[1]
        tree = json.loads(await self.world.fetch(headphones.TREE_URL, 4 * 1024 * 1024))
        result = {"source": headphones.PAGE, "collections": headphones.parse_tree(tree)}
        self._headphones = (time.monotonic(), result)
        return result

    async def apply_headphone_filter(self, path):
        """Download one model's filter, make it a FIR preset for every rate and switch to it."""
        from . import headphones
        listing = await self.headphone_list()
        item = next((i for c in listing["collections"] for i in c["items"] if i["path"] == path), None)
        if item is None:
            raise ValueError("Diesen Kopfhörer gibt es in der Liste nicht.")
        existing = next((p for p in self.config.data["dsp"]["presets"] if p.get("source") == path), None)
        if existing is None:
            data = await self.world.fetch(headphones.raw_url(path), headphones.MAX_BYTES)
            filters, peak = await asyncio.get_event_loop().run_in_executor(None, headphones.build, data)
            pid = "hp-" + uuid.uuid4().hex[:8]
            fir = {}
            for rate, pair in filters.items():
                for ch, taps in pair.items():
                    dst = f"{pid}_{ch}_{rate}.dbl"
                    atomic_write_bytes(self.data / "filters" / dst, taps.astype("<f8").tobytes())
                    fir.setdefault(str(rate), {})[ch] = dst
            existing = {"id": pid, "name": f"Kopfhörer: {item['name']}"[:40], "kind": "fir", "origin": "headphone",
                        "source": path, "fir": fir, "created": time.strftime("%Y-%m-%d"),
                        # headroom for the boost (bass), so nothing clips
                        "gain_db": -math.ceil(max(0.0, peak) * 2) / 2}
            self.save_preset(existing, activate=False)
        self.patch_config({"dsp": {"active_preset": existing["id"], "enabled": True}})
        return existing

    def import_fir(self, name, files):
        """files: {(channel, rate): (filename, bytes)} -> new FIR preset."""
        pid = "fir-" + uuid.uuid4().hex[:8]
        fir, problems = {}, []
        for (ch, rate), (fname, data) in files.items():
            taps = dsp.read_fir(data, fname)
            peak = dsp.fir_peak_db(taps)
            if peak > 6:
                problems.append(f"{fname}: Filter verstärkt um {peak:.1f} dB, Übersteuerung möglich.")
            dst = f"{pid}_{ch}_{rate}.dbl"
            atomic_write_bytes(self.data / "filters" / dst, taps.astype("<f8").tobytes())
            fir.setdefault(str(rate), {})[ch] = dst
        incomplete = [r for r, v in fir.items() if set(v) != {"L", "R"}]
        if incomplete:
            raise ValueError("Für jede Abtastrate braucht es eine Datei für links und rechts.")
        preset = {"id": pid, "name": name, "kind": "fir", "origin": "import", "fir": fir,
                  "created": time.strftime("%Y-%m-%d")}
        self.save_preset(preset, activate=False)
        return preset, problems

    def set_compare(self, bypass):
        self.compare_bypass = bool(bypass)
        self.apply_dsp()

    def preset_curve(self, pid, freqs):
        p = next((x for x in self.config.data["dsp"]["presets"] if x["id"] == pid), None)
        if p is None:
            raise KeyError(pid)
        out = {}
        for ch in ("L", "R"):
            if p["kind"] == "peq":
                db = dsp.biquad_response_db(p["peq"].get(ch, []), freqs, 48000)
            elif p["kind"] == "fir":
                rate = sorted(int(r) for r in p["fir"])[0]
                import numpy as np
                path = self.preset_dir(p) / p["fir"][str(rate)][ch]
                taps = np.fromfile(path, dtype="<f8") if path.exists() else np.array([1.0])
                db = dsp.fir_response_db(taps, freqs, rate)
            else:
                db = [0.0] * len(freqs)
            out[ch] = [round(float(x) + p.get("gain_db", 0) + p.get("trim_db", {}).get(ch, 0), 2) for x in db]
        return out

    # ── services ─────────────────────────────────────────────────────────────
    def service_login(self, provider, data):
        result = self.world.service_login(provider, data, self.secrets)
        self.publish_services()
        return result

    def service_logout(self, provider):
        self.secrets.delete_prefix(provider + ".")
        if hasattr(self.world, "service_logout"):
            self.world.service_logout(provider)
        self.publish_services()

    # ── system ───────────────────────────────────────────────────────────────
    async def check_update(self):
        self.update["state"] = "checking"
        self.publish_update()
        try:
            found = await self.world.check_update(self.config.get("update.channel"))
        except Exception:
            self.update["state"] = "idle"
            self.publish_update()
            raise
        self.update.update(state="idle", available=found["version"] if found else None,
                           notes=found["notes"] if found else [], checked=time.time())
        self.publish_update()

    async def install_update(self):
        if not self.update["available"]:
            raise ValueError("Kein Update verfügbar.")
        self.update.update(state="installing", progress=0)
        self.publish_update()
        try:
            async for progress in self.world.install_update(self.update["available"]):
                self.update["progress"] = progress
                self.publish_update()
        except Exception as exc:
            self.update.update(state="idle", progress=0)
            self.publish_update()
            self.hub.notice(str(exc) if isinstance(exc, ValueError) else "Das Update ist fehlgeschlagen.",
                            level="danger", key="update")
            raise
        self.update.update(state="reboot_required", progress=100)
        self.publish_update()

    async def reboot(self):
        self.hub.notice("Der Aroio startet neu …", key="reboot")
        self.hub.publish("system", {"rebooting": True, "since": time.time()})
        await self.world.reboot(self)
        self.reboot_required = False
        self.apply_dsp()
        self.publish_device()

    # ── factory filters (ABACUS, from AroioOS 5.1: BBC-Dip, Echo) ─────────────
    FACTORY_PRESETS = [("werk-bbcdip", "BBC-Dip", "BBCDip"), ("werk-echo", "Echo", "Echo")]

    def _factory_filters(self):
        """Device: /usr/share/aroio/filters (aroio-filters package). Development: the
        archive in the repository, unpacked once into the data directory."""
        dev = getattr(self.world, "factory_filter_dir", None)
        if dev and Path(dev).is_dir():
            return Path(dev)
        target = self.data / "factory-filters"
        archive = Path(__file__).parent / "factory" / "filter.tgz"
        if not target.is_dir() and archive.exists():
            import tarfile
            tmp = self.data / "factory-filters.tmp"
            tmp.mkdir(exist_ok=True)
            with tarfile.open(archive) as tar:
                for m in tar.getmembers():
                    name = Path(m.name).name
                    # the right channels are symlinks to the left ones in the 5.1 archive
                    if (m.isfile() or m.issym() or m.islnk()) and name.endswith(".dbl") and not name.startswith("Bypass"):
                        (tmp / name).write_bytes(tar.extractfile(m).read())
            tmp.rename(target)
        return target

    def _ensure_factory_presets(self):
        from .migration import RATE_TOKENS
        presets = self.config.data["dsp"]["presets"]
        have = {p["id"] for p in presets}
        added = []
        for pid, name, base in self.FACTORY_PRESETS:
            if pid in have:
                continue
            fir = {}
            for tok, rate in RATE_TOKENS.items():
                l_, r_ = f"{base}L{tok}.dbl", f"{base}R{tok}.dbl"
                if (self.factory_dir / l_).exists() and (self.factory_dir / r_).exists():
                    fir[str(rate)] = {"L": l_, "R": r_}
            if fir:
                added.append({"id": pid, "name": name, "kind": "fir", "origin": "builtin", "fir": fir})
        if added:
            self.config.patch({"dsp": {"presets": presets + added}})

    def preset_dir(self, preset):
        return self.factory_dir if preset.get("origin") == "builtin" and preset["id"].startswith("werk-") \
            else self.data / "filters"

    # ── boot configuration (aroio.txt): driver, model controls, display rotation ──
    def sound_card_missing(self):
        """No card to play on (e.g. "automatic" chosen, but the HAT has no readable EEPROM).
        HDMI does not count unless chosen on purpose ("onboard")."""
        if self.config.get("hardware.dac_driver") == "onboard":
            return False
        return not any(o["kind"] != "hdmi" for o in self.world.audio_outputs())

    def _boot_lines(self, hw):
        model = hw["model"] if hw["model"] in models.MODELS else self.world.model
        return models.boot_lines(hw["dac_driver"], model, hw["display_rotate"], ir=hw["ir_enabled"])

    def write_boot_config(self):
        self.world.write_boot_config(self._boot_lines(self.config.data["hardware"]))

    # ── room measurement mode ────────────────────────────────────────────────
    def begin_measurement(self):
        """Measure the room as it is: no correction, but the Cleaner stays (speakers with
        Cleaner expect M/S), volume at 0 dB (the level check finds the measuring level)."""
        if self.measuring:
            return
        self.pause()
        self.measuring = True
        self.world.set_volume(0.0)
        self.rate = 48000
        self.apply_dsp()

    def end_measurement(self):
        if not self.measuring:
            return
        self.measuring = False
        self.world.set_volume(0.0 if self.fixed_level else volume_db(0 if self.muted else self.volume))
        self.apply_dsp()

    # ── remote control (rc-core scancodes) ───────────────────────────────────
    def on_ir(self, scancode):
        code = hex(int(scancode))
        self.last_ir = code
        if self._ir_learn and not self._ir_learn.done():
            self._ir_learn.set_result(code)
            return True
        action = self.config.get("hardware.ir_map", {}).get(code)
        if action and self.config.get("hardware.ir_enabled"):
            return self.on_key(action)
        return False

    async def learn_ir(self, action, timeout=15.0):
        if action not in models.IR_ACTIONS:
            raise ValueError("Unbekannte Funktion")
        loop = asyncio.get_event_loop()
        self._ir_learn = loop.create_future()
        try:
            code = await asyncio.wait_for(self._ir_learn, timeout)
        except asyncio.TimeoutError:
            raise ValueError("Keine Taste empfangen. Bitte auf die Fernbedienung drücken, solange „Anlernen“ läuft.") from None
        finally:
            self._ir_learn = None
        ir_map = {c: a for c, a in self.config.get("hardware.ir_map", {}).items() if a != action}
        ir_map[code] = action
        self.patch_config({"hardware": {"ir_map": ir_map}})
        return code

    # ── misc device functions ────────────────────────────────────────────────
    def test_noise(self, channel):
        """Pink noise for setting up speakers and levels (None stops it)."""
        if channel not in (None, "L", "R", "both"):
            raise ValueError(channel)
        if channel:
            self.pause()
        self.world.test_noise(channel)

    def set_lyrion_credentials(self, user, password):
        self.secrets.set("lms.user", (user or "").strip() or None)
        self.secrets.set("lms.password", password or None)
        self.publish_services()

    def test_tone(self, channel):
        if channel not in ("L", "R", "both"):
            raise ValueError(channel)
        self.world.test_tone(channel)

    def factory_reset(self):
        self.stop()
        self.queue, self.index, self.source, self.meta = [], -1, None, None
        self.compare_bypass = False
        self.pending_migration = None
        if self.netsetup:
            self.netsetup.started = time.monotonic()      # grace period like after boot
            self.netsetup.attempt = {"state": "idle", "ssid": None, "error": None, "at": None}
        had_proxy = bool(self.proxy_url())
        self.config.reset()
        self.secrets.delete_prefix("")
        if had_proxy:
            self.world.proxy_apply("")
        self.library.favorites.clear()
        self.library.recent.clear()
        self.volume = self.config.get("audio.start_volume")
        self.muted = False
        for f in (self.data / "filters").glob("*"):
            f.unlink()
        if self.wizard:
            self.wizard.reset()
            self.wizard.publish()
        self.publish_all()
        self.apply_dsp()

    # ── migration ────────────────────────────────────────────────────────────
    def offer_migration(self, userconfig_text, filter_files, source="aroio-ng"):
        from .migration import migrate
        result = migrate(userconfig_text, list(filter_files))
        result["state"] = "review"
        result["source"] = source
        result["filter_data"] = filter_files
        self.pending_migration = result
        self.publish_migration()
        return result

    def apply_migration(self):
        m = self.pending_migration
        if not m:
            raise ValueError("Keine Übernahme vorbereitet.")
        for c in m["copies"]:
            data = m["filter_data"].get(c["from"])
            if data is not None:
                atomic_write_bytes(self.data / "filters" / c["to"], data)
        for key, value in m["secrets"].items():
            self.secrets.set(key, value)
        patch = {k: (dict(v) if isinstance(v, dict) else v) for k, v in m["patch"].items()}
        patch.setdefault("setup", {})["completed"] = False
        if "presets" in patch.get("dsp", {}):
            # keep the built-in ones (bypass, factory filters), add the old filter banks
            builtin = [p for p in self.config.data["dsp"]["presets"] if p.get("origin") == "builtin"]
            patch["dsp"]["presets"] = builtin + [p for p in patch["dsp"]["presets"] if p["id"] not in {b["id"] for b in builtin}]
        self.patch_config(patch)
        self.volume = self.config.get("audio.start_volume")
        m["state"] = "applied"
        self.publish_all()
        self.apply_dsp()

    def finish_migration(self):
        if self.pending_migration:
            self.pending_migration["state"] = "done"
        self.patch_config({"setup": {"completed": True}})
        self.pending_migration = None
        self.publish_migration()


def dsp_bypass():
    from .config import builtin_bypass
    return builtin_bypass()


__all__ = ["Device", "SOURCES", "Invalid", "PROVIDERS"]
