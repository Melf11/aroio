"""The device configuration: /data/config.json.

One JSON document with a declared schema and a version number. Every change
from the app is a partial update (patch) that is merged, validated against the
schema and then written atomically. Unknown keys are rejected, values are
type-checked and clamped, so a broken app request can never leave the device
in an unbootable state. Schema upgrades are code (UPGRADES) with tests.

This replaces /boot/userconfig.txt of the old system, which is read exactly
once, by aroiod.migration.
"""

import copy
import logging
import re
import threading

from .models import DAC_DRIVER_IDS, DEFAULT_IR_MAP, IR_ACTIONS, MODEL_IDS
from .store import atomic_write_json, load_json

log = logging.getLogger("aroiod.config")

VERSION = 2

RATES = [44100, 48000, 88200, 96000, 176400, 192000]
HOSTNAME_RE = r"^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$"
IPV4_RE = r"^((25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(25[0-5]|2[0-4]\d|1?\d?\d)$"


class Invalid(ValueError):
    """A patch was rejected. `path` names the offending key (dot notation)."""

    def __init__(self, path, message):
        super().__init__(f"{path}: {message}")
        self.path = path
        self.message = message


class F:
    """One scalar field of the schema."""

    def __init__(self, kind, default, choices=None, lo=None, hi=None, pattern=None,
                 empty_ok=True, maxlen=200):
        self.kind, self.default = kind, default
        self.choices, self.lo, self.hi = choices, lo, hi
        self.pattern = re.compile(pattern) if pattern else None
        self.empty_ok, self.maxlen = empty_ok, maxlen

    def check(self, path, value):
        if self.kind is bool:
            if not isinstance(value, bool):
                raise Invalid(path, "muss wahr/falsch sein")
            return value
        if self.kind is int:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise Invalid(path, "muss eine Zahl sein")
            value = int(round(value))
        elif self.kind is float:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise Invalid(path, "muss eine Zahl sein")
            value = float(value)
        elif self.kind is str:
            if not isinstance(value, str):
                raise Invalid(path, "muss Text sein")
            value = value.strip()
            if len(value) > self.maxlen:
                raise Invalid(path, f"höchstens {self.maxlen} Zeichen")
            if value == "" and self.empty_ok:
                return value
            if self.pattern and not self.pattern.match(value):
                raise Invalid(path, "ungültiges Format")
        if self.choices is not None and value not in self.choices:
            raise Invalid(path, f"erlaubt: {', '.join(map(str, self.choices))}")
        if self.lo is not None and value < self.lo:
            raise Invalid(path, f"mindestens {self.lo}")
        if self.hi is not None and value > self.hi:
            raise Invalid(path, f"höchstens {self.hi}")
        return value


def _addr():
    return F(str, "", pattern=IPV4_RE)


def _ipcfg():
    return {"dhcp": F(bool, True), "address": _addr(), "netmask": _addr(),
            "gateway": _addr(), "dns": _addr()}


SCHEMA = {
    "device": {
        "name": F(str, "Aroio", empty_ok=False, maxlen=40),
        "language": F(str, "de", choices=["de", "en"]),
        "theme": F(str, "auto", choices=["auto", "light", "dark"]),
        "expert_mode": F(bool, False),
    },
    "audio": {
        # follow: every source plays at its own rate, DSP reloads per rate
        # fixed: everything is resampled to fixed_rate
        "rate_mode": F(str, "follow", choices=["follow", "fixed"]),
        "fixed_rate": F(int, 96000, choices=RATES),
        "resampler": F(str, "balanced", choices=["fast", "balanced", "best"]),
        "start_volume": F(int, 30, lo=0, hi=100),
        "max_rate": F(int, 192000, choices=RATES),      # highest rate the DAC takes
        "volume_limit": F(int, 100, lo=10, hi=100),
        "output": F(str, "auto", maxlen=60),
        "chunksize": F(int, 0, lo=0, hi=65536),         # 0 = measured default
        "target_level": F(int, 0, lo=0, hi=262144),     # 0 = measured default
        "lms_buffer_kb": F(int, 0, lo=0, hi=200000),    # 0 = default
        "airplay_latency_ms": F(int, 0, lo=0, hi=5000),  # 0 = default
    },
    "dsp": {
        "enabled": F(bool, True),
        "active_preset": F(str, "bypass", maxlen=64),
        "ms_cleaner": F(bool, False),
        "character": F(str, "neutral", choices=["neutral", "warm", "bright"]),
        # presets: list, validated by check_presets()
    },
    "sources": {
        "lms": {"enabled": F(bool, True), "server": F(str, "", maxlen=253),
                "port": F(int, 9000, lo=1, hi=65535)},
        "spotify": {"enabled": F(bool, True)},
        "airplay": {"enabled": F(bool, True)},
        "upnp": {"enabled": F(bool, True)},
        "bluetooth": {"enabled": F(bool, True), "auto_reconnect": F(bool, True),
                      "codec": F(str, "auto", choices=["auto", "ldac", "aptx_hd", "aac", "sbc"])},
        "input": {"enabled": F(bool, False)},
        "roon": {"enabled": F(bool, False)},
        # NetJack 2: the Aroio is the master, computers with JACK connect as slaves
        "netjack": {"enabled": F(bool, False), "rate": F(int, 48000, choices=[44100, 48000, 88200, 96000])},
    },
    "services": {
        "tidal": {"enabled": F(bool, False)},
        "qobuz": {"enabled": F(bool, False)},
        # where TIDAL/Qobuz/library come from: own Lyrion on the Aroio or the
        # customer's server. auto = own server only when no other is found.
        "lyrion_local": F(str, "auto", choices=["auto", "on", "off"]),
    },
    "network": {
        "hostname": F(str, "aroio", pattern=HOSTNAME_RE, empty_ok=False, maxlen=63),
        "lan": _ipcfg(),
        "wifi": dict(_ipcfg(), enabled=F(bool, True), ssid=F(str, "", maxlen=32)),
        "hotspot": F(str, "auto", choices=["auto", "off"]),
    },
    "hardware": {
        "display_rotate": F(int, 0, choices=[0, 90, 180, 270]),
        # "auto" matches the neutral aroio.txt of the image; the setup guide picks the real one
        "dac_driver": F(str, "auto", choices=DAC_DRIVER_IDS),
        "model": F(str, "auto", choices=["auto"] + MODEL_IDS),
        # ir_map: {"0x180d": "KEY_MUTE", ...}, validated by check_ir_map()
        "onboard_bluetooth": F(bool, True),
        "ir_enabled": F(bool, True),
        "encoder_step": F(int, 2, lo=1, hi=10),
    },
    "update": {
        "channel": F(str, "stable", choices=["stable", "beta"]),
        "auto": F(bool, True),
    },
    "security": {
        "ssh": F(bool, False),
        "app_password": F(bool, False),
    },
    "setup": {
        "completed": F(bool, False),
        "migrated_from": F(str, "", maxlen=40),
    },
}

PRESET_KINDS = ["bypass", "peq", "fir"]
PEQ_TYPES = ["peaking", "lowshelf", "highshelf", "lowpass", "highpass"]


def defaults(schema=SCHEMA):
    out = {}
    for key, spec in schema.items():
        out[key] = defaults(spec) if isinstance(spec, dict) else copy.deepcopy(spec.default)
    return out


def default_config():
    cfg = defaults()
    cfg["version"] = VERSION
    cfg["dsp"]["presets"] = [builtin_bypass()]
    cfg["hardware"]["ir_map"] = dict(DEFAULT_IR_MAP)
    return cfg


def builtin_bypass():
    return {"id": "bypass", "name": "Ohne Korrektur", "kind": "bypass", "gain_db": 0.0,
            "delay_ms": {"L": 0.0, "R": 0.0}, "trim_db": {"L": 0.0, "R": 0.0}, "origin": "builtin"}


def _check_filter(path, f):
    if not isinstance(f, dict):
        raise Invalid(path, "Filter muss ein Objekt sein")
    out = {
        "type": F(str, "peaking", choices=PEQ_TYPES).check(path + ".type", f.get("type", "peaking")),
        "freq": F(float, 1000.0, lo=10, hi=24000).check(path + ".freq", f.get("freq", 1000.0)),
        "gain": F(float, 0.0, lo=-24, hi=12).check(path + ".gain", f.get("gain", 0.0)),
        "q": F(float, 0.7, lo=0.1, hi=20).check(path + ".q", f.get("q", 0.7)),
    }
    return out


def check_presets(value):
    if not isinstance(value, list) or len(value) > 32:
        raise Invalid("dsp.presets", "Liste mit höchstens 32 Einträgen")
    out, seen = [], set()
    for i, p in enumerate(value):
        path = f"dsp.presets[{i}]"
        if not isinstance(p, dict):
            raise Invalid(path, "muss ein Objekt sein")
        pid = F(str, "", pattern=r"^[a-z0-9_-]{1,64}$", empty_ok=False).check(path + ".id", p.get("id", ""))
        if pid in seen:
            raise Invalid(path + ".id", "doppelt")
        seen.add(pid)
        kind = F(str, "peq", choices=PRESET_KINDS).check(path + ".kind", p.get("kind", "peq"))
        item = {
            "id": pid,
            "name": F(str, "", empty_ok=False, maxlen=40).check(path + ".name", p.get("name", "")),
            "kind": kind,
            "gain_db": F(float, 0.0, lo=-40, hi=12).check(path + ".gain_db", p.get("gain_db", 0.0)),
            "delay_ms": {ch: F(float, 0.0, lo=0, hi=100).check(f"{path}.delay_ms.{ch}",
                                                                  (p.get("delay_ms") or {}).get(ch, 0.0))
                         for ch in ("L", "R")},
            "trim_db": {ch: F(float, 0.0, lo=-20, hi=6).check(f"{path}.trim_db.{ch}",
                                                                (p.get("trim_db") or {}).get(ch, 0.0))
                        for ch in ("L", "R")},
            "origin": F(str, "user", choices=["builtin", "user", "roomcorr", "import", "migration", "headphone"]).check(
                path + ".origin", p.get("origin", "user")),
        }
        if kind == "peq":
            peq = p.get("peq") or {}
            item["peq"] = {}
            for ch in ("L", "R"):
                filters = peq.get(ch) or []
                if not isinstance(filters, list) or len(filters) > 20:
                    raise Invalid(f"{path}.peq.{ch}", "höchstens 20 Filter")
                item["peq"][ch] = [_check_filter(f"{path}.peq.{ch}[{j}]", f) for j, f in enumerate(filters)]
        if kind == "fir":
            fir = p.get("fir") or {}
            item["fir"] = {}
            for rate, files in fir.items():
                if int(rate) not in RATES or not isinstance(files, dict):
                    raise Invalid(f"{path}.fir.{rate}", "ungültige Abtastrate")
                item["fir"][str(int(rate))] = {
                    ch: F(str, "", pattern=r"^[A-Za-z0-9_.-]{1,100}$", empty_ok=False).check(
                        f"{path}.fir.{rate}.{ch}", files.get(ch, "")) for ch in ("L", "R")}
        if "measurement" in p:
            item["measurement"] = F(str, "", pattern=r"^[a-z0-9_-]{1,64}$").check(
                path + ".measurement", p["measurement"])
        if "created" in p:
            item["created"] = F(str, "", maxlen=40).check(path + ".created", p["created"])
        if "source" in p:      # where a downloaded filter came from (headphone filter project path)
            item["source"] = F(str, "", maxlen=200, pattern=r"^[^\x00-\x1f]*$").check(path + ".source", p["source"])
        out.append(item)
    if "bypass" not in seen:
        out.insert(0, builtin_bypass())
    return out


def check_ir_map(value):
    if not isinstance(value, dict) or len(value) > 64:
        raise Invalid("hardware.ir_map", "höchstens 64 Tasten")
    out = {}
    for code, action in value.items():
        if not re.fullmatch(r"0x[0-9a-f]{1,8}", str(code)):
            raise Invalid(f"hardware.ir_map.{code}", "ungültiger Code")
        if action not in IR_ACTIONS:
            raise Invalid(f"hardware.ir_map.{code}", "unbekannte Funktion")
        out[str(code)] = action
    return out


def _merge(path, schema, current, patch):
    if not isinstance(patch, dict):
        raise Invalid(path or "config", "muss ein Objekt sein")
    for key, value in patch.items():
        sub = f"{path}.{key}" if path else key
        if path == "dsp" and key == "presets":
            current["presets"] = check_presets(value)
            continue
        if path == "hardware" and key == "ir_map":
            current["ir_map"] = check_ir_map(value)
            continue
        if key not in schema:
            raise Invalid(sub, "unbekannte Einstellung")
        spec = schema[key]
        if isinstance(spec, dict):
            _merge(sub, spec, current.setdefault(key, {}), value)
        else:
            current[key] = spec.check(sub, value)


def _fill(schema, cfg):
    """Add missing keys with defaults, drop unknown keys (after an upgrade)."""
    for key, spec in schema.items():
        if isinstance(spec, dict):
            if not isinstance(cfg.get(key), dict):
                cfg[key] = {}
            _fill(spec, cfg[key])
        elif key not in cfg:
            cfg[key] = copy.deepcopy(spec.default)
        else:
            try:
                cfg[key] = spec.check(key, cfg[key])
            except Invalid:
                log.warning("Invalid stored value for %s, using default", key)
                cfg[key] = copy.deepcopy(spec.default)
    for key in [k for k in cfg if k not in schema and k not in ("presets", "version", "ir_map")]:
        del cfg[key]


# version n -> n+1. Each function gets and returns the whole document.
def _wifi_switch_to_network(cfg):
    """1 -> 2: hardware.onboard_wifi did nothing on the device; network.wifi.enabled is the switch."""
    hw = cfg.get("hardware")
    if isinstance(hw, dict) and hw.pop("onboard_wifi", True) is False:
        net = cfg.setdefault("network", {})
        if isinstance(net, dict):
            wifi = net.setdefault("wifi", {})
            if isinstance(wifi, dict):
                wifi["enabled"] = False
    return cfg


UPGRADES = {1: _wifi_switch_to_network}


def upgrade(cfg):
    version = int(cfg.get("version", 1))
    while version < VERSION:
        cfg = UPGRADES[version](cfg)
        version += 1
    cfg["version"] = VERSION
    return cfg


def normalise(cfg):
    cfg = upgrade(copy.deepcopy(cfg))
    _fill(SCHEMA, cfg)
    try:
        cfg["dsp"]["presets"] = check_presets(cfg["dsp"].get("presets", []))
    except Invalid as exc:
        log.warning("Invalid stored presets (%s), keeping only bypass", exc)
        cfg["dsp"]["presets"] = [builtin_bypass()]
    try:
        cfg["hardware"]["ir_map"] = check_ir_map(cfg["hardware"].get("ir_map", DEFAULT_IR_MAP))
    except Invalid:
        cfg["hardware"]["ir_map"] = dict(DEFAULT_IR_MAP)
    if cfg["dsp"]["active_preset"] not in {p["id"] for p in cfg["dsp"]["presets"]}:
        cfg["dsp"]["active_preset"] = "bypass"
    return cfg


class Config:
    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        stored = load_json(path, None)
        self.data = normalise(stored) if stored else default_config()
        if stored != self.data:
            atomic_write_json(self.path, self.data)

    def get(self, dotted, default=None):
        node = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def patch(self, patch):
        """Validate and apply a partial update. Returns the new config.
        Raises Invalid without changing anything if any value is wrong."""
        with self._lock:
            candidate = copy.deepcopy(self.data)
            _merge("", SCHEMA, candidate, patch)
            presets = {p["id"] for p in candidate["dsp"]["presets"]}
            if candidate["dsp"]["active_preset"] not in presets:
                raise Invalid("dsp.active_preset", "unbekanntes Preset")
            if candidate != self.data:
                atomic_write_json(self.path, candidate)
                self.data = candidate
            return self.data

    def reset(self):
        with self._lock:
            self.data = default_config()
            atomic_write_json(self.path, self.data)
