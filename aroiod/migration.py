"""Take over an old Aroio (aroio-ng / AroioOS 4.x): /boot/userconfig.txt + /boot/filter.

    report = migrate(userconfig_text, filter_files)

returns a config patch for aroiod.config plus a report the migration wizard
shows item by item ("übernommen" / "bitte prüfen" / "entfällt"), and secrets.
Nothing is written here; the wizard applies the result after confirmation.

Keys, defaults and legacy 3.x names follow aroio-ng/usr/bin/checkuserconfig.
"""

import re
import shlex

RATE_TOKENS = {44: 44100, 48: 48000, 88: 88200, 96: 96000, 176: 176400, 192: 192000}
FILTER_RE = re.compile(r"^(?P<name>.+?)(?P<ch>[LR])(?P<rate>44|48|88|96|176|192)\.dbl$")

# old default values: a value equal to these is not "user-tuned" and is dropped
OLD_DEFAULTS = {"SQUEEZE_ALSABUFFER": "", "SQUEEZE_INTBUFFER": "", "SP_OUTBUFFER": "", "JACKBUFFER": "4096"}


def parse_userconfig(text):
    """Shell-style KEY="value" lines. Never executes anything."""
    out = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[7:].strip()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            continue
        try:
            parts = shlex.split(value, comments=True)
            value = parts[0] if parts else ""
        except ValueError:
            value = value.strip().strip('"').strip("'")
        out[key] = value
    return out


def _on(v):
    return str(v).strip().upper() in ("ON", "YES", "TRUE", "1")


def _int(v, default=None):
    try:
        return int(float(str(v).strip()))
    except (TypeError, ValueError):
        return default


class Report:
    def __init__(self):
        self.items = []

    def add(self, area, label, value, status="ok", note=""):
        self.items.append({"area": area, "label": label, "value": value, "status": status, "note": note})


def _hostname(name):
    h = re.sub(r"[^a-zA-Z0-9-]", "-", name).strip("-")[:63]
    return h or "aroio"


def migrate(text, filter_files=()):
    """text: userconfig.txt content. filter_files: names found in /boot/filter.
    Returns {"patch", "secrets", "report", "copies"}; copies maps old filter
    file names to safe names under /data/filters."""
    u = parse_userconfig(text)
    rep, patch, secrets = Report(), {}, {}

    # legacy 3.x names (checkuserconfig)
    for old, new in (("IPADDR", "LAN_IPADDR"), ("NETMASK", "LAN_NETMASK"), ("GATEWAY", "LAN_GATEWAY"),
                     ("DNSSERV", "LAN_DNSSERV"), ("DHCP", "LAN_DHCP")):
        if u.get(old) and not u.get(new):
            u[new] = u[old]

    # ── device ──
    host = u.get("HOSTNAME", "")
    if host in ("", "(none)"):
        host = "AroioOS"
    player = u.get("PLAYERNAME", "")
    if player in ("", "(none)"):
        player = host
    patch["device"] = {"name": player[:40]}
    patch["network"] = {"hostname": _hostname(host)}
    rep.add("Gerät", "Name", player)
    if _hostname(host) != host:
        rep.add("Gerät", "Netzwerkname", _hostname(host), "check",
                f"„{host}“ enthält Zeichen, die im Netzwerk nicht erlaubt sind.")

    # ── network ──
    lan = {"dhcp": True}
    if u.get("LAN_DHCP") and not _on(u.get("LAN_DHCP")):
        if all(u.get(k) for k in ("LAN_IPADDR", "LAN_NETMASK", "LAN_GATEWAY", "LAN_DNSSERV")):
            lan = {"dhcp": False, "address": u["LAN_IPADDR"], "netmask": u["LAN_NETMASK"],
                   "gateway": u["LAN_GATEWAY"], "dns": u["LAN_DNSSERV"]}
            rep.add("Netzwerk", "LAN", f"feste Adresse {u['LAN_IPADDR']}")
        else:
            rep.add("Netzwerk", "LAN", "automatisch (DHCP)", "check",
                    "Feste Adresse war unvollständig, deshalb automatisch.")
    else:
        rep.add("Netzwerk", "LAN", "automatisch (DHCP)")
    patch["network"]["lan"] = lan

    ssid = u.get("WLANSSID", "")
    if ssid and ssid != "AroioAP":
        wifi = {"enabled": True, "ssid": ssid[:32], "dhcp": True}
        if u.get("WLAN_DHCP") and not _on(u.get("WLAN_DHCP")) and all(
                u.get(k) for k in ("WLAN_IPADDR", "WLAN_NETMASK", "WLAN_GATEWAY", "WLAN_DNSSERV")):
            wifi.update({"dhcp": False, "address": u["WLAN_IPADDR"], "netmask": u["WLAN_NETMASK"],
                         "gateway": u["WLAN_GATEWAY"], "dns": u["WLAN_DNSSERV"]})
        patch["network"]["wifi"] = wifi
        if u.get("WLANPWD"):
            secrets["wifi.psk"] = u["WLANPWD"]
        rep.add("Netzwerk", "WLAN", ssid)
    elif ssid == "AroioAP":
        rep.add("Netzwerk", "WLAN", "Einrichtungs-Hotspot", "info",
                "Das alte Gerät war im Hotspot-Modus. Der neue Aroio öffnet den Hotspot nur, solange kein Netz eingerichtet ist.")

    # ── hardware ──
    hw = {}
    if u.get("ONBOARD_WIFI") and not _on(u["ONBOARD_WIFI"]):
        patch.setdefault("network", {}).setdefault("wifi", {})["enabled"] = False
    if u.get("ONBOARD_BLUETOOTH"):
        hw["onboard_bluetooth"] = _on(u["ONBOARD_BLUETOOTH"])
    rot = _int(u.get("DISPLAY_ROTATE"))
    if rot is not None:
        # old values: 0..3 (config.txt display_rotate) or degrees
        hw["display_rotate"] = {0: 0, 1: 90, 2: 180, 3: 270}.get(rot, rot if rot in (90, 180, 270) else 0)
    if hw:
        patch["hardware"] = hw

    platform = u.get("PLATFORM", "")
    if platform:
        rep.add("Gerät", "Modell", platform, "info", "Das Modell wird jetzt automatisch erkannt und verglichen.")

    # ── audio + sources ──
    audio = {}
    rate = _int(u.get("RATE"))
    if rate in RATE_TOKENS.values():
        audio["rate_mode"] = "follow"
        audio["fixed_rate"] = rate
        rep.add("Ton", "Abtastrate", "folgt jetzt der Musik", "info",
                f"Bisher wurde alles auf {rate / 1000:g} kHz umgerechnet. Der neue Aroio spielt jede Datei in ihrer "
                "eigenen Abtastrate. Feste Rate ist im Expertenmodus wählbar.")
    res = u.get("RESAMPLING", "")
    if res:
        audio["resampler"] = {"speexrate": "fast", "speexrate_medium": "balanced", "speexrate_best": "best"}.get(res, "balanced")
    vol = _int(u.get("VOLUME_START", u.get("VOL_START")))
    if vol is not None:
        # old: attenuation in dB (0 = full). New: percent. -60 dB..0 dB -> 0..100
        audio["start_volume"] = max(0, min(100, round(100 + vol * 100 / 60))) if vol <= 0 else 100
        rep.add("Ton", "Startlautstärke", f"{audio['start_volume']} %")
    tuned = []
    for key, target in (("SQUEEZE_ALSABUFFER", None), ("SQUEEZE_INTBUFFER", "lms_buffer_kb"),
                        ("SP_OUTBUFFER", None), ("JACKBUFFER", None), ("JACKPERIOD", None), ("BF_PARTITIONS", None)):
        if u.get(key) and u[key] != OLD_DEFAULTS.get(key):
            tuned.append(f"{key}={u[key]}")
            if target and _int(u[key]):
                audio[target] = _int(u[key])
    if tuned:
        rep.add("Ton", "Puffer-Einstellungen", ", ".join(tuned), "info",
                "Der neue Tonweg hat eigene, gemessene Puffer. Werte findest du im Expertenmodus.")
    if audio:
        patch["audio"] = audio

    output = u.get("AUDIO_OUTPUT", "")
    ms = _on(u.get("MSCODING", "OFF")) or output in ("vol-plug-ms", "jack-bfms", "jack-ms", "vol-plug-dmix-ms")
    bf = _on(u.get("BRUTEFIR", "OFF")) or output in ("jack-bf", "jack-bfms")
    patch["dsp"] = {"enabled": True, "ms_cleaner": ms}
    rep.add("Klang", "Cleaner (M/S)", "an" if ms else "aus")

    sources = {}
    raw = (u.get("RAW_PLAYERMS") if ms else u.get("RAW_PLAYER")) or u.get("RAW_PLAYER", "")
    used = set()
    if output.startswith("vol-plug") and "dmix" not in output and raw:
        used.add(raw)
    prefix = {"jack": "JACK_", "jack-ms": "JACKMS_", "jack-bf": "JACKBF_", "jack-bfms": "JACKBFMS_",
              "vol-plug-dmix": "DMIX_", "vol-plug-dmix-ms": "DMIXMS_"}.get(output)
    names = {"SQUEEZELITE": "squeezelite", "SHAIRPORTSYNC": "shairportsync", "GMEDIARENDER": "gmediarender",
             "BLUEALSAAPLAY": "bluealsaaplay", "SPOTIFYD": "spotifyd", "INPUT": "input", "NETJACK": "netjack"}
    if prefix:
        for k, v in names.items():
            if _on(u.get(prefix + k, "OFF")):
                used.add(v)
    mapping = {"squeezelite": "lms", "shairportsync": "airplay", "gmediarender": "upnp",
               "bluealsaaplay": "bluetooth", "spotifyd": "spotify", "librespot": "spotify", "input": "input",
               "netjack": "netjack"}
    if used:
        for src in ("lms", "airplay", "upnp", "bluetooth", "spotify", "input", "netjack"):
            sources[src] = {"enabled": any(mapping.get(x) == src for x in used)}
    labels = {"lms": "Lyrion/LMS", "airplay": "AirPlay", "upnp": "UPnP/DLNA", "bluetooth": "Bluetooth",
              "spotify": "Spotify", "input": "Eingang", "netjack": "NetJack"}
    on = [labels[s] for s, v in sources.items() if v["enabled"]]
    if on:
        rep.add("Quellen", "Aktive Quellen", ", ".join(on))
    else:
        rep.add("Quellen", "Aktive Quellen", "alle Standardquellen", "info")

    srv = u.get("SERVERNAME", "")
    lms = {}
    if srv:
        lms["server"] = srv
        rep.add("Quellen", "Lyrion-Server", srv)
    else:
        rep.add("Quellen", "Lyrion-Server", "wird automatisch gesucht")
    port = _int(u.get("SERVERPORT"))
    if port and port != 3483:
        # the old field held the player port (3483); web/JSON port stays 9000 unless set
        lms["port"] = port if port != 9090 else 9000
    if lms or "lms" in sources:
        sources.setdefault("lms", {}).update(lms)
    if u.get("SQUEEZEUSER"):
        secrets["lms.user"] = u["SQUEEZEUSER"]
        secrets["lms.password"] = u.get("SQUEEZEPWD", "")
    if _on(u.get("BTRECONNECT", "OFF")) or "BTRECONNECT" in u:
        sources.setdefault("bluetooth", {})["auto_reconnect"] = _on(u.get("BTRECONNECT", "OFF"))
    if sources:
        patch["sources"] = sources
    if "spotify" in sources and sources["spotify"]["enabled"]:
        rep.add("Quellen", "Spotify", "neu verbinden", "check",
                "Spotify läuft im neuen Aroio anders und muss einmal neu verbunden werden.")

    # ── filter banks -> presets ──
    by_name = {}
    for f in filter_files:
        m = FILTER_RE.match(f)
        if m:
            by_name.setdefault(m["name"], {}).setdefault(RATE_TOKENS[int(m["rate"])], {})[m["ch"]] = f
    presets, active, copies = [], "bypass", []
    def_coeff = u.get("DEF_COEFF", "0")
    for i in range(10):
        name = u.get(f"COEFF_NAME{i}", "")
        if not name or name == "BypassFilter":
            continue
        rates = {r: files for r, files in by_name.get(name, {}).items() if set(files) == {"L", "R"}}
        pid = f"bank{i}"
        factory = {"BBCDip": "werk-bbcdip", "Echo": "werk-echo"}.get(name)
        if not rates and factory:
            # ABACUS factory filter from the old system (LOAD_PREFILTER): built into the new one
            rep.add("Klang", f"Filterbank {i + 1}: {name}", "Werksfilter, im neuen Aroio eingebaut")
            if str(i) == str(def_coeff) and bf:
                active = factory
            continue
        if not rates:
            rep.add("Klang", f"Filterbank {i + 1}: {name}", "Filterdateien fehlen", "check",
                    f"Für „{name}“ wurden keine Dateien gefunden. Bitte die Filter neu hochladen.")
            continue
        att = _int(u.get(f"COEFF_ATT{i}"), 0) or 0
        delay = _int(u.get(f"COEFF_DELAY{i}"), 0) or 0
        fir = {}
        for r, files in rates.items():
            fir[str(r)] = {}
            for ch in ("L", "R"):
                dst = f"{pid}_{ch}_{r}.dbl"
                copies.append({"from": files[ch], "to": dst})
                fir[str(r)][ch] = dst
        preset = {"id": pid, "name": name[:40], "kind": "fir", "gain_db": float(-abs(att)),
                  "origin": "migration", "fir": fir}
        if delay:
            ms_val = round(delay * 1000.0 / (rate or 96000), 3)
            preset["delay_ms"] = {"L": ms_val, "R": ms_val}
            rep.add("Klang", f"Filterbank {i + 1}: Verzögerung", f"{ms_val} ms", "check",
                    f"Alter Wert {delay} wurde als Samples bei {(rate or 96000) / 1000:g} kHz gelesen.")
        presets.append(preset)
        missing = sorted(set(RATE_TOKENS.values()) - set(rates))
        note = ""
        if missing:
            note = ("Filter fehlen für " + ", ".join(f"{r / 1000:g}" for r in missing) +
                    " kHz. Bei Musik in diesen Abtastraten wird auf eine vorhandene Rate umgerechnet.")
        rep.add("Klang", f"Filterbank {i + 1}", f"{name} ({', '.join(f'{r / 1000:g}' for r in sorted(rates))} kHz)",
                "check" if missing else "ok", note)
        if str(i) == str(def_coeff) and bf:
            active = pid
    if presets:
        patch["dsp"]["presets"] = presets
    if presets or active != "bypass":
        patch["dsp"]["active_preset"] = active
    elif bf:
        rep.add("Klang", "Raumkorrektur", "keine Filter gefunden", "check",
                "BruteFIR war an, aber es wurden keine Filterdateien gefunden.")

    # ── system ──
    if _on(u.get("USEBETA", "OFF")):
        patch["update"] = {"channel": "beta"}
        rep.add("System", "Updates", "Beta-Kanal")
    if u.get("USERPASSWD"):
        patch["security"] = {"app_password": True}
        secrets["app.password"] = u["USERPASSWD"]
        rep.add("System", "Passwort für die App", "übernommen")
    for key in ("MEASUREMENT_OUTPUT", "LOAD_PREFILTER", "KNOWN_VERSION", "UPDATESERVER"):
        if key in u:
            rep.add("System", key, "entfällt", "dropped")

    patch["setup"] = {"migrated_from": "aroio-ng"}
    return {"patch": patch, "secrets": secrets, "report": rep.items,
            "copies": copies}


SAMPLE_USERCONFIG = """\
HOSTNAME="Wohnzimmer"
PLAYERNAME="Aroio Wohnzimmer"
PLATFORM="AroioLT"
LAN_DHCP="OFF"
LAN_IPADDR="192.168.1.50"
LAN_NETMASK="255.255.255.0"
LAN_GATEWAY="192.168.1.1"
LAN_DNSSERV="192.168.1.1"
WLANSSID="AroioAP"
WLANPWD=""
ONBOARD_WIFI="OFF"
ONBOARD_BLUETOOTH="ON"
RATE="96000"
RESAMPLING="speexrate_medium"
VOLUME_START="-20"
AUDIO_OUTPUT="jack-bfms"
MSCODING="ON"
BRUTEFIR="ON"
JACKBFMS_SQUEEZELITE="ON"
JACKBFMS_SHAIRPORTSYNC="ON"
JACKBFMS_BLUEALSAAPLAY="OFF"
JACKBFMS_SPOTIFYD="ON"
JACKBFMS_NETJACK="OFF"
SERVERNAME="192.168.1.10"
SERVERPORT="9000"
SQUEEZE_INTBUFFER="40000"
JACKBUFFER="4096"
COEFF_NAME0="Wohnzimmer"
COEFF_ATT0="3"
COEFF_DELAY0="0"
COEFF_NAME1="Abacus C-Box"
COEFF_ATT1="0"
COEFF_NAME2="BypassFilter"
DEF_COEFF="0"
BTRECONNECT="ON"
DISPLAY_ROTATE="0"
USEBETA="OFF"
USERPASSWD=""
MEASUREMENT_OUTPUT="jack-bf"
"""

SAMPLE_FILTERS = ["WohnzimmerL44.dbl", "WohnzimmerR44.dbl", "WohnzimmerL48.dbl", "WohnzimmerR48.dbl",
                  "WohnzimmerL96.dbl", "WohnzimmerR96.dbl", "Abacus C-BoxL96.dbl", "Abacus C-BoxR96.dbl"]
