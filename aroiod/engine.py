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
import time
import uuid
from pathlib import Path

from . import dsp, models
from .config import Config, Invalid
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
}


def volume_db(percent):
    """0..100 % -> dB. Steeper at the bottom like an analogue pot."""
    if percent <= 0:
        return None  # mute
    return round(-60.0 * (1 - percent / 100) ** 1.6, 1)


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
        self.library.enabled = lambda p: p == "local" or self.config.get(f"services.{p}.enabled", False)
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
        self.dsp_status = {}
        self._end_task = None
        self.update = {"current": VERSION, "available": None, "state": "idle", "progress": 0,
                       "notes": [], "checked": None}
        self.pending_migration = None
        self.reboot_required = False
        self.wizard = None          # set by app (wizard.RoomWizard)
        self.netsetup = None        # set by app (netsetup.NetSetup)

    # ── helpers ──────────────────────────────────────────────────────────────
    @property
    def model(self):
        return models.MODELS[self.world.model]

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
        self.publish_all()
        self.apply_dsp()

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
            "model": self.world.model, "model_label": self.model["label"],
            "board": self.world.board, "board_label": board["label"],
            "fixed_level": self.fixed_level, "has_input": self.model["has_input"] or c["sources"]["input"]["enabled"],
            "version": VERSION, "setup_completed": c["setup"]["completed"],
            "reboot_required": self.reboot_required,
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
            "can": {"seek": bool(self.meta and self.meta.get("duration")) and self.source in ("lms", "spotify"),
                    "next": self.source in ("lms", "spotify", "airplay", "bluetooth", "upnp", "roon"),
                    "previous": self.source in ("lms", "spotify", "airplay", "bluetooth", "upnp", "roon"),
                    "queue": self.source == "lms", "shuffle": self.source in ("lms", "spotify")},
            "signal": sig,
        })

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
            item = {k: p[k] for k in ("id", "name", "kind", "origin", "gain_db") if k in p}
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
            "lyrion": self.world.lyrion_status(c),
            "airplay": {"enabled": c["sources"]["airplay"]["enabled"]},
            "upnp": {"enabled": c["sources"]["upnp"]["enabled"]},
            "roon": {"enabled": c["sources"]["roon"]["enabled"]},
        })

    def publish_network(self):
        status = self.world.network_status(self.config.data)
        if self.netsetup:
            status.update(self.netsetup.status())
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
        if not d["enabled"] or self.compare_bypass:
            return dsp_bypass()
        return next((p for p in d["presets"] if p["id"] == d["active_preset"]), dsp_bypass())

    def apply_dsp(self):
        """(Re)build the CamillaDSP config for the current rate and preset."""
        c = self.config.data
        rate_in = self.rate
        preset = self.active_preset()
        fixed = c["audio"]["rate_mode"] == "fixed"
        rate_out = c["audio"]["fixed_rate"] if fixed else rate_in
        note = None
        if preset["kind"] == "fir":
            have = sorted(int(r) for r in preset.get("fir", {}))
            if rate_out not in have:
                # nearest available rate, prefer same family (44.1k / 48k multiples)
                family = [r for r in have if (r % 44100 == 0) == (rate_out % 44100 == 0)] or have
                rate_out = min(family, key=lambda r: abs(r - rate_out))
                note = "missing_rate"
        try:
            cfg = dsp.camilla_config(
                preset, rate_out, ms_cleaner=c["dsp"]["ms_cleaner"] and c["dsp"]["enabled"],
                fir_dir=str(self.data / "filters"), playback=self.world.dac_device,
                capture_rate=rate_in if rate_in != rate_out else None, resampler=c["audio"]["resampler"],
                chunksize=c["audio"]["chunksize"] or None, target_level=c["audio"]["target_level"] or None)
        except dsp.MissingRate:
            cfg = dsp.camilla_config(dsp_bypass(), rate_in, playback=self.world.dac_device)
            note = "error"
        self.world.camilla_apply(cfg)
        taps = 0
        if preset["kind"] == "fir":
            taps = self.world.fir_taps(self.data / "filters", preset, rate_out)
        limit = models.fir_limit(self.world.board, rate_out)
        self.dsp_status = {"rate_in": rate_in, "rate_out": rate_out, "resampled": rate_in != rate_out,
                           "pipeline_empty": dsp.is_bit_perfect(cfg),
                           "processing": bool(cfg["pipeline"]), "note": note,
                           "preset": preset["name"], "fir_taps": taps,
                           "too_heavy": bool(taps and taps > limit), "fir_limit": limit,
                           "load": self.world.dsp_load(cfg, taps)}
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
        if rate:
            self.set_rate(rate)
        self.publish_player()
        self.publish_sources()
        return True

    def source_stopped(self, sid):
        if self.source == sid:
            self._freeze()
            self.state = "stopped" if sid in ("bluetooth", "input", "airplay") else "paused"
            self.publish_player()
            self.publish_sources()

    def external_meta(self, sid, meta):
        if self.source == sid:
            self.meta = meta
            self.pos_base, self.started_at = 0.0, time.monotonic() if self.state == "playing" else None
            if meta.get("format", {}).get("rate"):
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
        self._freeze()
        self.state = "paused"
        if self.source != "lms":
            self.world.pause_source(self.source)
        self.publish_player()
        self.publish_sources()

    def toggle(self):
        self.pause() if self.state == "playing" else self.play()

    def stop(self):
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
        elif self.source:
            self.world.source_command(self.source, "next")

    def previous(self):
        if self.source == "lms":
            if self.position() > 3 or self.index == 0:
                self.seek(0)
            else:
                self._start_track(self.index - 1)
        elif self.source:
            self.world.source_command(self.source, "previous")

    def seek(self, seconds):
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
            self.publish_network()
        if "hardware" in changed and after["hardware"]["dac_driver"] != before["hardware"]["dac_driver"]:
            self.world.set_dac_driver(after["hardware"]["dac_driver"])
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
        if pid == "bypass":
            raise ValueError("„Ohne Korrektur“ kann nicht gelöscht werden.")
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
                path = self.data / "filters" / p["fir"][str(rate)][ch]
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
        self.publish_services()

    # ── system ───────────────────────────────────────────────────────────────
    async def check_update(self):
        self.update["state"] = "checking"
        self.publish_update()
        found = await self.world.check_update(self.config.get("update.channel"))
        self.update.update(state="idle", available=found["version"] if found else None,
                           notes=found["notes"] if found else [], checked=time.time())
        self.publish_update()

    async def install_update(self):
        if not self.update["available"]:
            raise ValueError("Kein Update verfügbar.")
        self.update.update(state="installing", progress=0)
        self.publish_update()
        async for progress in self.world.install_update(self.update["available"]):
            self.update["progress"] = progress
            self.publish_update()
        self.update.update(state="reboot_required", progress=100)
        self.publish_update()

    async def reboot(self):
        self.hub.notice("Der Aroio startet neu …", key="reboot")
        await self.world.reboot(self)
        self.reboot_required = False
        self.apply_dsp()
        self.publish_device()

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
        self.config.reset()
        self.secrets.delete_prefix("")
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
        patch = dict(m["patch"])
        patch.setdefault("setup", {})["completed"] = False
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
