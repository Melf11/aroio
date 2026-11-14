"""Room correction wizard: one step per screen, state lives here, the app only
renders it (topic "roomcorr") and sends actions.

    intro -> mic -> placement -> level -> measure (n positions x L/R)
          -> character -> compute -> result (A/B) -> done

The maths is aroiod.roomcorr; playing the sweep and recording the microphone
is world.measure() (simulated room in the simulator, ALSA in phase 3).
"""

import asyncio
import logging
import time
import uuid

import numpy as np

from . import dsp
from . import roomcorr as rc
from .config import Invalid, _check_filter
from .store import atomic_write_json

log = logging.getLogger("aroiod.wizard")

STEPS = [("intro", "Los geht’s"), ("mic", "Mikrofon"), ("placement", "Aufstellen"), ("level", "Lautstärke"),
         ("measure", "Messen"), ("character", "Klangcharakter"), ("result", "Ergebnis")]
RATE = 48000


class RoomWizard:
    def __init__(self, device):
        self.device = device
        self.world = device.world
        self.reset()

    def reset(self):
        self.active = False
        self.step = "intro"
        self.positions = 3
        self.current = 0
        self.measurements = {}        # (position, channel) -> {"curve", "peak"}
        self.busy = None              # text of what is running
        self.progress = 0.0
        self.level = None
        self.character = self.device.config.get("dsp.character")
        self.result = None
        self.calibration = None
        self.calibration_name = None
        self.error = None
        self.previous_preset = None
        self.comparing = False
        self.saved = None
        self.issue = None
        self._task = None

    # ── state for the app ──
    def state(self):
        mic = self.world.mic_status()
        if mic.get("calibration") and not self.calibration:
            self.calibration = mic["calibration"]
            self.calibration_name = mic.get("calibration_name")
        done = [{"position": p, "channel": ch} for (p, ch) in sorted(self.measurements)]
        return {
            "active": self.active, "step": self.step,
            "steps": [{"id": s, "title": t} for s, t in STEPS],
            "step_index": [s for s, _ in STEPS].index(self.step),
            "mic": {"connected": mic["connected"], "name": mic.get("name"), "serial": mic.get("serial"),
                    "calibration": bool(self.calibration), "calibration_name": self.calibration_name},
            "positions": self.positions, "current": self.current, "measured": done,
            "busy": self.busy, "progress": round(self.progress, 3), "level": self.level,
            "character": self.character, "result": self.result, "error": self.error,
            "issue": self.issue, "comparing": self.comparing, "saved": self.saved,
        }

    def publish(self):
        self.device.hub.publish("roomcorr", self.state())

    # ── actions ──
    async def action(self, name, data):
        if self.busy and name not in ("cancel",):
            raise ValueError("Bitte warten, bis der laufende Schritt fertig ist.")
        fn = getattr(self, "a_" + name, None)
        if fn is None:
            raise ValueError(f"Unbekannte Aktion {name}")
        self.error = None
        result = fn(**(data or {}))
        if asyncio.iscoroutine(result):
            await result
        self.publish()

    def a_start(self):
        self.reset()
        self.active = True
        self.step = "intro"

    def a_goto(self, step):
        order = [s for s, _ in STEPS]
        if step not in order or order.index(step) > order.index(self.step):
            raise ValueError("Dieser Schritt ist noch nicht dran.")
        if step in ("intro", "mic", "placement", "level", "measure") and self.comparing:
            self._end_compare(restore=True)
        self.step = step

    def a_next(self):
        if self.step == "intro":
            self.step = "mic"
        elif self.step == "mic":
            if not self.world.mic_status()["connected"]:
                raise ValueError("Es ist noch kein Messmikrofon angeschlossen.")
            self.step = "placement"
        elif self.step == "placement":
            self.step = "level"
        elif self.step == "level":
            if not self.level or self.level["status"] != "ok":
                raise ValueError("Bitte zuerst die Lautstärke prüfen.")
            self.step = "measure"
        elif self.step == "measure":
            if len(self.measurements) < self.positions * 2:
                raise ValueError("Es fehlen noch Messungen.")
            self.step = "character"
        elif self.step == "character":
            raise ValueError("Bitte „Berechnen“ wählen.")

    def a_back(self):
        order = [s for s, _ in STEPS]
        i = order.index(self.step)
        if i > 0:
            if self.comparing:
                self._end_compare(restore=True)
            self.step = order[i - 1]

    def a_set_positions(self, count):
        count = int(count)
        if not 1 <= count <= 9:
            raise ValueError("1 bis 9 Messpositionen")
        self.positions = count
        self.measurements = {k: v for k, v in self.measurements.items() if k[0] < count}
        self.current = min(self.current, count - 1)

    def a_calibration(self, text, name="Kalibrierung"):
        try:
            serial, pairs = rc.parse_calibration(text)
        except ValueError as exc:
            raise ValueError(str(exc)) from None
        self.calibration = pairs
        self.calibration_name = name + (f" ({serial})" if serial else "")

    async def a_level(self):
        """Pink noise ramps up until the mic sees about 75 dB SPL; never above the limit."""
        self.device.pause()
        self.busy = "Rauschen wird langsam lauter …"
        self.publish()
        try:
            async for progress, result in self.world.level_check():
                self.progress = progress
                self.publish()
            self.level = result
        finally:
            self.busy, self.progress = None, 0.0

    async def a_measure(self):
        if self.step != "measure":
            raise ValueError("Jetzt wird nicht gemessen.")
        p = self.current
        self.device.pause()          # the measurement needs the speakers alone
        sweep, inverse = rc.log_sweep(RATE, seconds=self.world.sweep_seconds)
        self.issue = None
        try:
            for i, ch in enumerate(("L", "R")):
                self.busy = f"Messe {'linken' if ch == 'L' else 'rechten'} Lautsprecher …"
                self.progress = i / 2
                self.publish()
                rec = await self.world.measure(sweep, ch, p, progress=self._sub_progress(i))
                curve, peak, issue = await asyncio.get_event_loop().run_in_executor(
                    None, self._analyse, rec, inverse)
                if issue:
                    self.issue = issue
                    for c in ("L", "R"):
                        self.measurements.pop((p, c), None)
                    return
                self.measurements[(p, ch)] = {"curve": curve, "peak": peak}
            if p + 1 < self.positions:
                self.current = p + 1
        finally:
            self.busy, self.progress = None, 0.0

    def _sub_progress(self, i):
        def cb(x):
            self.progress = (i + x) / 2
            self.publish()
        return cb

    def _analyse(self, rec, inverse):
        peak_level = 20 * np.log10(max(np.max(np.abs(rec)), 1e-12))
        if peak_level > -0.5:
            return None, None, {"kind": "clipping", "text": "Das Mikrofon war übersteuert. Wir messen etwas leiser noch einmal."}
        ir, peak = rc.impulse_response(rec, inverse)
        noise = np.std(ir[: max(1, peak - int(0.05 * RATE))])
        snr = 20 * np.log10(abs(ir[peak]) / max(noise, 1e-12))
        if snr < 50:
            return None, None, {"kind": "noise", "text": "Es war zu laut im Raum (Störgeräusch). Bitte für die Messung ruhig sein und noch einmal messen."}
        freqs, db = rc.magnitude(ir, peak, RATE)
        db = rc.apply_calibration(freqs, db, self.calibration)
        _, curve = rc.smooth(freqs, db, fraction=6)
        return curve, int(peak), None

    def a_select_position(self, position):
        position = int(position)
        if not 0 <= position < self.positions:
            raise ValueError("Position gibt es nicht")
        self.current = position

    def a_set_character(self, character):
        if character not in rc.CHARACTERS:
            raise ValueError(character)
        self.character = character

    async def a_compute(self):
        self.busy = "Berechne die Korrektur …"
        self.publish()
        try:
            curves = {}
            for ch in ("L", "R"):
                curves[ch] = rc.average([m["curve"] for (p, c), m in self.measurements.items() if c == ch])
            fmax = 500.0 if not self.device.config.get("device.expert_mode") else self.world.fmax
            result = await asyncio.get_event_loop().run_in_executor(
                None, lambda: rc.correct(curves, self.character, fmax=fmax))
            # time alignment from position 0: delay the nearer speaker
            pl, pr = self.measurements[(0, "L")]["peak"], self.measurements[(0, "R")]["peak"]
            diff_ms = (pr - pl) * 1000.0 / RATE
            result["delay_ms"] = {"L": round(max(0.0, diff_ms), 3), "R": round(max(0.0, -diff_ms), 3)}
            result["distance_cm"] = round(abs(diff_ms) * 34.3, 1)
            result["fmax"] = fmax
            for c in result["channels"].values():
                c["auto_filters"] = [dict(f) for f in c["filters"]]
            self.result = result
            self.step = "result"
            self._start_compare()
        finally:
            self.busy = None

    def a_set_filters(self, channel, filters):
        """Manual adjustment of the calculated filters. channel: L, R or both."""
        if not self.result:
            raise ValueError("Es gibt noch kein Ergebnis.")
        if channel not in ("L", "R", "both"):
            raise ValueError("Kanal L, R oder both")
        if not isinstance(filters, list) or len(filters) > 20:
            raise ValueError("Höchstens 20 Filter")
        try:
            clean = [_check_filter(f"filters[{i}]", f) for i, f in enumerate(filters)]
        except Invalid as exc:
            raise ValueError(exc.message) from None
        for ch in (("L", "R") if channel == "both" else (channel,)):
            self._set_channel_filters(ch, [dict(f) for f in clean])
        self._refresh_preview()

    def a_reset_filters(self):
        if not self.result:
            raise ValueError("Es gibt noch kein Ergebnis.")
        for ch, c in self.result["channels"].items():
            self._set_channel_filters(ch, [dict(f) for f in c["auto_filters"]])
        self._refresh_preview()

    def _set_channel_filters(self, ch, filters):
        r = self.result
        c = r["channels"][ch]
        freqs = np.asarray(r["freqs"])
        before, target = np.asarray(c["before"]), np.asarray(c["target"])
        after = before + dsp.biquad_response_db(filters, freqs)
        band = (freqs >= rc.FMIN) & (freqs <= r["fmax"])
        c["filters"] = filters
        c["after"] = np.round(after, 2).tolist()
        c["deviation_after"] = round(float(np.sqrt(np.mean((after[band] - target[band]) ** 2))), 2)
        c["manual"] = filters != c["auto_filters"]

    def _refresh_preview(self):
        r = self.result
        r["headroom_db"] = dsp.headroom_db({ch: c["filters"] for ch, c in r["channels"].items()})
        if self.comparing:
            active = self.device.config.get("dsp.active_preset") == "preview"
            self.device.save_preset(self._preset("preview", "Neue Messung (Vorschau)"), activate=active)

    def _preset(self, pid, name):
        r = self.result
        return {"id": pid, "name": name, "kind": "peq", "origin": "roomcorr",
                "peq": {ch: r["channels"][ch]["filters"] for ch in ("L", "R")},
                "trim_db": r["trim_db"], "delay_ms": r["delay_ms"],
                "gain_db": r["headroom_db"], "created": time.strftime("%Y-%m-%d")}

    def _start_compare(self):
        if self.previous_preset is None:
            self.previous_preset = self.device.config.get("dsp.active_preset")
        self.device.save_preset(self._preset("preview", "Neue Messung (Vorschau)"), activate=True)
        self.comparing = True

    def _end_compare(self, restore):
        presets = [p for p in self.device.config.data["dsp"]["presets"] if p["id"] != "preview"]
        patch = {"dsp": {"presets": presets}}
        if restore:
            patch["dsp"]["active_preset"] = self.previous_preset or "bypass"
        elif self.device.config.get("dsp.active_preset") == "preview":
            patch["dsp"]["active_preset"] = "bypass"
        self.device.patch_config(patch)
        self.comparing = False

    def a_listen(self, which):
        """A/B: 'new' = preview preset, 'old' = what was active before."""
        if not self.comparing:
            raise ValueError("Kein Vergleich aktiv.")
        target = "preview" if which == "new" else (self.previous_preset or "bypass")
        self.device.patch_config({"dsp": {"active_preset": target}})

    def a_save(self, name):
        name = (name or "").strip()[:40] or "Raumkorrektur"
        pid = "rc-" + uuid.uuid4().hex[:8]
        self._end_compare(restore=False)
        r = self.result
        atomic_write_json(self.device.data / "measurements" / f"{pid}.json", {
            "freqs": r["freqs"], "fmax": r["fmax"], "character": self.character,
            "channels": {ch: {k: c[k] for k in ("before", "target", "auto_filters")} for ch, c in r["channels"].items()}})
        preset = self._preset(pid, name)
        preset["measurement"] = pid
        self.device.save_preset(preset, activate=True)
        self.device.patch_config({"dsp": {"character": self.character, "enabled": True}})
        self.saved = {"id": pid, "name": name}
        self.step = "result"
        self.active = False

    def a_cancel(self):
        if self.comparing:
            self._end_compare(restore=True)
        self.world.stop_measurement()
        self.reset()
