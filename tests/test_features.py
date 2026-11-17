"""Functions taken over from AroioOS 5.1 and the rest of the gap list."""

import asyncio
import zipfile
from io import BytesIO

import pytest

from aroiod import inputs, models
from aroiod.migration import migrate


async def post(client, path, data=None, status=200):
    r = await client.post("/api/v1" + path, json=data or {})
    body = await r.json()
    assert r.status == status, body
    return body


async def state(client):
    return await (await client.get("/api/v1/state")).json()


async def test_own_equalizer_without_microphone(client, device):
    p = await post(client, "/dsp/presets", {})
    assert p["kind"] == "peq" and p["origin"] == "user" and p["name"] == "Eigener Equalizer"
    assert [f["type"] for f in p["peq"]["L"]] == ["lowshelf", "peaking", "highshelf"]
    assert all(f["gain"] == 0 for f in p["peq"]["L"] + p["peq"]["R"])
    s = await state(client)
    assert s["dsp"]["active_preset"] == p["id"] and s["dsp"]["enabled"]
    second = await post(client, "/dsp/presets", {})
    assert second["name"] == "Eigener Equalizer 2"


def test_loudness_of_presets():
    from aroiod import dsp
    assert dsp.loudness_db({"kind": "peq", "gain_db": -3.0, "peq": {"L": [], "R": []}}) == -3.0
    bass_cut = {"kind": "peq", "gain_db": 0.0,
                "peq": {ch: [{"type": "lowshelf", "freq": 200.0, "gain": -6.0, "q": 0.7}] for ch in "LR"}}
    assert -3.0 < dsp.loudness_db(bass_cut) < -0.3          # a bass cut makes music quieter, a bit
    boost = {"kind": "peq", "gain_db": -6.0,
             "peq": {ch: [{"type": "peaking", "freq": 1000.0, "gain": 6.0, "q": 1.0}] for ch in "LR"}}
    assert -6.0 < dsp.loudness_db(boost) < -2.0               # headroom minus the boost's share


async def test_compare_without_correction_is_loudness_matched(client, device):
    p = await post(client, "/dsp/presets", {})
    peq = {ch: [{"type": "lowshelf", "freq": 100.0, "gain": 6.0, "q": 0.7}] for ch in "LR"}
    r = await client.patch(f"/api/v1/dsp/presets/{p['id']}", json={"peq": peq})
    assert r.status == 200
    preset = next(x for x in device.config.get("dsp.presets") if x["id"] == p["id"])
    assert preset["gain_db"] < 0                               # automatic headroom for the boost
    await post(client, "/dsp/compare", {"bypass": True})
    status = (await state(client))["dsp"]["status"]
    from aroiod import dsp
    expected = min(0.0, dsp.loudness_db(preset, status["rate_out"]))
    assert status["compare_gain_db"] == expected and expected < 0
    cfg = device.apply_dsp()
    assert cfg["filters"]["preset_gain"]["parameters"]["gain"] == expected
    assert not any(k.startswith("peq_") for k in cfg["filters"])     # no correction, only the level
    await post(client, "/dsp/compare", {"bypass": False})
    assert (await state(client))["dsp"]["status"]["compare_gain_db"] is None


async def test_factory_filters(client, device):
    ids = {p["id"]: p for p in device.config.get("dsp.presets")}
    assert {"werk-bbcdip", "werk-echo"} <= set(ids)
    assert set(ids["werk-bbcdip"]["fir"]) == {"44100", "48000", "88200", "96000", "176400", "192000"}
    await post(client, "/dsp/presets/werk-bbcdip/activate")
    device.set_rate(96000)
    fname = device.world.camilla["filters"]["fir_L"]["parameters"]["filename"]
    assert fname.endswith("factory-filters/BBCDipL96.dbl")
    assert device.dsp_status["fir_taps"] == 65536
    r = await client.delete("/api/v1/dsp/presets/werk-echo")
    assert r.status == 400
    curve = await (await client.get("/api/v1/dsp/presets/werk-bbcdip/curve")).json()
    assert len(curve["channels"]["L"]) == len(curve["freqs"])


async def test_max_rate(client, device):
    await client.patch("/api/v1/config", json={"audio": {"max_rate": 96000}})
    device.set_rate(192000)
    assert device.dsp_status["rate_out"] == 96000 and device.dsp_status["note"] == "max_rate"
    device.set_rate(176400)
    assert device.dsp_status["rate_out"] == 88200            # same family: 44.1 kHz multiples
    assert device.world.camilla["devices"]["capture_samplerate"] == 176400


async def test_model_choice_and_boot_config(client, device):
    assert models.boot_lines("aroio", "AroioLT")[-2:] == [
        "dtoverlay=rotary-encoder,pin_a=23,pin_b=24,relative_axis=1",
        'dtoverlay=gpio-key,gpio=27,keycode=164,label="PLAYPAUSE"']
    await client.patch("/api/v1/config", json={"hardware": {"model": "AroioEX", "display_rotate": 180}})
    s = await state(client)
    assert s["device"]["model"] == "AroioEX" and s["device"]["fixed_level"] and s["device"]["reboot_required"]
    assert "display_rotate=2" in device.world.boot_lines
    assert any("gpio-key" in l for l in device.world.boot_lines)
    assert not any("rotary-encoder" in l for l in device.world.boot_lines)


async def test_measurement_mode_keeps_cleaner_and_recordings(client, device):
    await client.patch("/api/v1/config", json={"dsp": {"ms_cleaner": True}})
    device.save_preset({"id": "eq", "name": "EQ", "kind": "peq", "peq": {"L": [{"type": "peaking", "freq": 50, "gain": -6, "q": 2}], "R": []}})
    await post(client, "/player/volume", {"value": 20})
    device.begin_measurement()
    cfg = device.world.camilla
    assert [s.get("name") for s in cfg["pipeline"]] == ["cleaner"]    # correction off, Cleaner on
    assert device.world.volume_db == 0.0
    device.end_measurement()
    assert any(s.get("names") for s in device.world.camilla["pipeline"])
    assert device.world.volume_db < 0
    # full wizard -> recordings for Acourate
    rc = lambda a, d=None: post(client, "/roomcorr/" + a, d)  # noqa: E731
    await post(client, "/sim/mic", {"on": True})
    for a in ("start", "next", "next", "next", "level", "next"):
        await rc(a)
    await rc("set_positions", {"count": 1})
    await rc("measure")
    await rc("next")
    await rc("compute")
    r = await client.get("/api/v1/roomcorr/recordings.zip")
    assert r.status == 200
    names = zipfile.ZipFile(BytesIO(await r.read())).namelist()
    assert {"position1_L.wav", "position1_R.wav", "sweep.wav", "info.txt"} <= set(names)
    assert (await state(client))["dsp"]["status"]["recordings"]


async def test_app_password(client, device):
    r = await client.get("/api/v1/auth/status")
    assert (await r.json()) == {"enabled": False, "logged_in": True}
    await post(client, "/security/password", {"password": "abc"}, status=400)
    r = await client.post("/api/v1/security/password", json={"password": "geheim"})
    assert r.status == 200
    client.session.cookie_jar.clear()
    r = await client.get("/api/v1/state")
    assert r.status == 401 and (await r.json())["login"]
    await post(client, "/auth/login", {"password": "falsch"}, status=400)
    await post(client, "/auth/login", {"password": "geheim"})
    assert (await client.get("/api/v1/state")).status == 200
    assert (await client.get("/api/v1/internal/status")).status == 200     # localhost, info screen
    await post(client, "/security/password", {"password": None})
    client.session.cookie_jar.clear()
    assert (await client.get("/api/v1/state")).status == 200


def test_legacy_password_is_hashed(device):
    device.secrets.set("app.password", "alt123")
    from aroiod.auth import Auth
    a = Auth(device)
    assert device.secrets.get("app.password") is None and a.check("alt123")


async def test_remote_control(client, device):
    await post(client, "/player/volume", {"value": 40})
    await post(client, "/sim/ir", {"code": "0x1810"})            # Aroio remote: volume up (default map)
    assert (await state(client))["player"]["volume"] > 40
    task = asyncio.create_task(client.post("/api/v1/hardware/ir/learn", json={"action": "KEY_MUTE"}))
    await asyncio.sleep(0.1)
    await post(client, "/sim/ir", {"code": "0xabcd"})
    r = await task
    assert (await r.json())["code"] == "0xabcd"
    assert device.config.get("hardware.ir_map")["0xabcd"] == "KEY_MUTE"
    await post(client, "/sim/ir", {"code": "0xabcd"})
    assert (await state(client))["player"]["muted"] is True
    await post(client, "/hardware/ir/reset")
    assert "0xabcd" not in device.config.get("hardware.ir_map")


def test_input_events():
    text = ('I: Bus=0019\nN: Name="gpio_ir_recv"\nH: Handlers=kbd event0 \n\n'
            'I: Bus=0019\nN: Name="rotary@17"\nH: Handlers=event1 \n')
    assert inputs.list_devices(text) == [("gpio_ir_recv", "event0"), ("rotary@17", "event1")]
    raw = inputs.EVENT.pack(0, 0, inputs.EV_MSC, inputs.MSC_SCAN, 0x1835) + inputs.EVENT.pack(0, 0, 2, 0, -1)
    assert inputs.decode(raw) == [(4, 4, 0x1835), (2, 0, -1)]

    class D:
        calls = []
        def on_ir(self, c): self.calls.append(("ir", c))
        def on_encoder(self, s): self.calls.append(("enc", s))
        def on_key(self, k): self.calls.append(("key", k))
    d = D()
    r = inputs.InputReader(d)
    for ev in inputs.decode(raw) + [(1, 164, 1), (1, 164, 2), (1, 115, 2)]:
        r.handle(*ev)
    assert d.calls == [("ir", 0x1835), ("enc", -1), ("key", "KEY_PLAYPAUSE"), ("key", "KEY_VOLUMEUP")]


async def test_misc_endpoints(client, device):
    await post(client, "/system/test-noise", {"channel": "L"})
    assert device.world.request["kind"] == "signal" and device.world.request["signal_kind"] == "noise"
    await post(client, "/system/test-noise", {"channel": None})
    assert device.world.request["kind"] == "signal_stop"
    r = await client.delete("/api/v1/bluetooth/devices")
    assert r.status == 200 and (await state(client))["bluetooth"]["devices"] == []
    lic = await (await client.get("/api/v1/system/licenses")).json()
    assert any(c["name"] == "CamillaDSP" for c in lic["components"])
    await post(client, "/services/lyrion/credentials", {"user": "anna", "password": "x"})
    ly = (await state(client))["services"]["lyrion"]
    assert ly["protected"] and ly["user"] == "anna" and ly["web"].startswith("http://192.168.1.10:")
    net = (await state(client))["network"]
    assert net["lan"]["mac"] and net["wifi"]["mac"]
    for unit in ("system", "audio", "airplay", "spotify", "bluetooth", "network", "kernel"):
        assert (await client.get("/api/v1/system/logs", params={"unit": unit})).status == 200


def test_migration_factory_filter():
    r = migrate('AUDIO_OUTPUT="jack-bf"\nBRUTEFIR="ON"\nCOEFF_NAME0="BBCDip"\nDEF_COEFF="0"\n', [])
    assert r["patch"]["dsp"]["active_preset"] == "werk-bbcdip"
    assert "presets" not in r["patch"]["dsp"]


def _item(typ, code, data=None):
    import base64
    h = lambda s: s.encode().hex()  # noqa: E731
    out = f"<item><type>{h(typ)}</type><code>{h(code)}</code><length>{len(data or b'')}</length>"
    if data is not None:
        out += f'\n<data encoding="base64">\n{base64.b64encode(data).decode()}</data>'
    return (out + "</item>\n").encode()


async def test_airplay_metadata(client, device):
    from aroiod.airplay_meta import AirplayMeta
    a = AirplayMeta(device, path="/nonexistent")
    jpeg = b"\xff\xd8\xff\xe0" + b"x" * 100
    stream = (_item("ssnc", "snam", b"Melfs iPhone") + _item("ssnc", "pbeg") + _item("ssnc", "mdst")
              + _item("core", "minm", "Blue in Green".encode()) + _item("core", "asar", b"Miles Davis")
              + _item("core", "asal", b"Kind of Blue") + _item("core", "astm", (337000).to_bytes(4, "big"))
              + _item("ssnc", "mden") + _item("ssnc", "PICT", jpeg) + _item("ssnc", "prgr", b"1000/45100/14862700"))
    a.handle_bytes(stream[:150])                       # items may arrive split
    a.handle_bytes(stream[150:])
    a._pending and a._pending.cancel()
    a._send()
    p = (await state(client))["player"]
    assert p["source"] == "airplay"
    t = p["track"]
    assert (t["title"], t["artist"], t["album"]) == ("Blue in Green", "Miles Davis", "Kind of Blue")
    assert t["image"].startswith("/api/v1/cover/airplay?v=") and t["controller"] == "Melfs iPhone"
    assert abs(t["duration"] - 337.0) < 0.1 and 0.9 < p["position"] < 1.5
    device.world.cover = lambda provider: a.cover()
    r = await client.get(t["image"])
    assert r.status == 200 and r.content_type == "image/jpeg"
    a.handle_bytes(_item("ssnc", "pend"))
    assert (await state(client))["player"]["state"] == "stopped"


def test_dacp_lookup():
    from aroiod.airplay_meta import pick_dacp
    browse = ("+;wlan0;IPv4;iTunes_Ctrl_ABCDEF0123456789;_dacp._tcp;local\n"
              "=;wlan0;IPv6;iTunes_Ctrl_ABCDEF0123456789;_dacp._tcp;local;iPhone.local;fe80::1;50123;\n"
              "=;wlan0;IPv4;iTunes_Ctrl_ABCDEF0123456789;_dacp._tcp;local;iPhone.local;192.168.1.50;50123;\n"
              "=;wlan0;IPv4;iTunes_Ctrl_1111111111111111;_dacp._tcp;local;Mac.local;192.168.1.60;50999;\n")
    assert pick_dacp(browse, "ABCDEF0123456789") == ("192.168.1.50", 50123)          # IPv4 before link-local
    assert pick_dacp(browse, "ABCDEF0123456789", clip="fe80::1%wlan0") == ("fe80::1%wlan0", 50123)
    assert pick_dacp(browse, "2222222222222222") is None


async def test_airplay_remote_control_keeps_session(client, device):
    """Pause/next in the app go to the iPhone (DACP) instead of ending the AirPlay session."""
    from aiohttp import web
    from aroiod.airplay_meta import AirplayMeta
    got = []

    async def ctrl(request):
        got.append((request.match_info["cmd"], request.headers.get("Active-Remote")))
        return web.Response(status=204)
    app = web.Application()
    app.router.add_get("/ctrl-int/1/{cmd}", ctrl)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        a = AirplayMeta(device, path="/nonexistent")
        assert not await a.command("pause")                       # no session yet
        a.handle_bytes(_item("ssnc", "daid", b"ABCDEF0123456789") + _item("ssnc", "acre", b"1234567")
                       + _item("ssnc", "clip", b"127.0.0.1") + _item("ssnc", "pbeg"))
        a._dacp["ABCDEF0123456789"] = ("127.0.0.1", port)
        assert await a.command("nextitem") and got[-1] == ("nextitem", "1234567")
        a.handle_bytes(_item("ssnc", "pend"))                     # pause ends the play block, not the session
        assert await a.command("play") and got[-1][0] == "play"
    finally:
        await runner.cleanup()


async def test_airplay2_remote_control_over_dbus(device, monkeypatch):
    """Shairport Sync 5.6: Pause/Next go through its D-Bus interface (AirPlay 2)."""
    from aroiod import airplay_meta as am
    calls = []

    async def fake_exec(*cmd):
        calls.append(cmd)
        return True, ""
    monkeypatch.setattr(am, "_exec", fake_exec)
    a = am.AirplayMeta(device, path="/nonexistent")
    assert not a.can_control()
    assert await a.command("pause")
    assert a.can_control()
    assert calls[-1][-1] == "Pause" and "org.gnome.ShairportSync.RemoteControl" in calls[-1]
    assert await a.command("nextitem") and calls[-1][-1] == "Next"


async def test_pause_from_app_keeps_sender_and_sender_pause_shows(client, device):
    calls = []
    device.world.pause_source = lambda sid, user=False: calls.append((sid, user))
    device.source_started("airplay", {"title": "x", "format": {"rate": 44100}})
    device.pause()
    assert calls == [("airplay", True)]
    device.source_resumed("airplay")                              # iPhone plays again
    assert (await state(client))["player"]["state"] == "playing"
    device.source_paused("airplay")                               # iPhone paused
    assert (await state(client))["player"]["state"] == "paused"
    device.source_started("bluetooth", {"title": "y", "format": {"rate": 44100}})
    assert calls[-1] == ("airplay", False)                        # switching still lets go of the loopback


async def test_player_shows_only_working_controls(client, device):
    """AirPlay 2 without remote control: only ending the session, no play/skip."""
    calls = []
    device.world.source_controls = lambda sid: {"stop"}
    device.world.pause_source = lambda sid, user=False: calls.append((sid, user))
    device.world.resume_source = lambda sid: calls.append((sid, "resume"))
    device.world.source_command = lambda sid, cmd: calls.append((sid, cmd))
    device.source_started("airplay", {"title": "x", "format": {"rate": 44100}})
    can = (await state(client))["player"]["can"]
    assert can["stop"] and not (can["pause"] or can["play"] or can["next"] or can["previous"] or can["seek"])
    device.next()
    device.pause()                                   # buttons on the device: pause = end the session
    assert calls == [("airplay", False)]
    assert (await state(client))["player"]["state"] == "stopped"
    device.play()                                    # cannot be started from the Aroio
    assert calls == [("airplay", False)] and (await state(client))["player"]["state"] == "stopped"


def test_real_airplay_controls_need_remote():
    from aroiod.real import RealWorld
    from aroiod.airplay_meta import AirplayMeta
    w = RealWorld()
    w.airplay = AirplayMeta(None, path="/nonexistent")
    assert w.source_controls("airplay") == {"stop"}
    w.airplay.track.remote = {"daid": "AB", "acre": "1"}
    assert "next" in w.source_controls("airplay")
    assert w.source_controls("spotify") == set() and w.source_controls("input") == set()   # Soloist not running


def test_bluetooth_parsers():
    from aroiod import bt_watch as bw
    pcms = "/org/bluealsa/hci0/dev_AA_BB_CC_DD_EE_FF/a2dpsnk/source\n/org/bluealsa/hci0/dev_AA_BB_CC_DD_EE_FF/a2dpsrc/sink\n"
    assert bw.parse_pcms(pcms) == [("/org/bluealsa/hci0/dev_AA_BB_CC_DD_EE_FF/a2dpsnk/source", "AA:BB:CC:DD:EE:FF")]
    info = "Device: /org/bluez/hci0/dev_AA\nTransport: A2DP-sink\nSelected codec: AAC\nRate: 44100\nRunning: true\n"
    assert bw.parse_running(info) and not bw.parse_running(info.replace("true", "false"))
    assert bw.parse_codec(info) == ("AAC", 44100)
    track = ('{"type":"a{sv}","data":{"Title":{"type":"s","data":"So What"},"Artist":{"type":"s","data":"Miles Davis"},'
             '"Duration":{"type":"u","data":562000}}}')
    assert bw.parse_track(track) == {"title": "So What", "artist": "Miles Davis", "album": "", "duration": 562.0}


async def test_bluetooth_watch_switches_source(client, device, monkeypatch):
    from aroiod import bt_watch as bw
    out = {"list": "", "info": ""}

    async def fake_out(*cmd, timeout=4):
        if cmd[1] == "list-pcms":
            return out["list"]
        if cmd[1] == "info":
            return out["info"]
        return ""
    monkeypatch.setattr(bw, "_out", fake_out)
    w = bw.BluetoothWatch(device)
    w.STOP_AFTER = 0
    device.source_started("airplay", {"title": "x", "format": {"rate": 44100}})
    out["list"] = "/org/bluealsa/hci0/dev_AA_BB_CC_DD_EE_FF/a2dpsnk/source"
    out["info"] = "Selected codec: SBC\nRate: 48000\nRunning: true\n"
    await w.poll()
    p = (await state(client))["player"]
    assert p["source"] == "bluetooth" and p["state"] == "playing" and device.rate == 48000
    out["info"] = "Running: false\n"
    await w.poll()
    await w.poll()
    assert (await state(client))["player"]["state"] == "stopped"


async def test_remote_volume_from_phone(client, device):
    from aroiod.airplay_meta import AirplayMeta
    from aroiod import bt_watch as bw
    a = AirplayMeta(device, path="/nonexistent")
    a.handle_bytes(_item("ssnc", "pbeg"))
    a.handle_bytes(_item("ssnc", "pvol", b"-15.00,-30.00,-96.30,0.00"))
    assert (await state(client))["player"]["volume"] == 50
    assert bw.parse_volume("Volume: L: 64 R: 64\n") == 50
    assert bw.parse_codec("Selected codec: SBC\nSampling: 44100 Hz\n") == ("SBC", 44100)


def test_loopback_format():
    from aroiod.real import loopback_params
    assert loopback_params("format: S16_LE\nrate: 44100 (44100/1)\n") == (44100, "S16_LE")
    assert loopback_params("format: S24_LE\nrate: 96000 (96000/1)\n") == (96000, "S24_4_RJ_LE")
    assert loopback_params("closed\n") is None


def test_soloist_helpers(tmp_path, monkeypatch):
    from aroiod import soloist
    assert soloist.parse_version("soloist 1.3.10.71 build 1794592912 (20261113) (g19412df6ea) (linux/aarch64)") \
        == ("1.3.10.71", "20261113")
    import pytest
    with pytest.raises(ValueError):
        soloist.clean_key("kurz")
    assert soloist.clean_key(" abcdef0123456789\nabcdef ") == "abcdef0123456789abcdef"
    monkeypatch.setattr(soloist, "ENV", tmp_path / "soloist.env")
    soloist.write_key("abcdef0123456789")
    assert (tmp_path / "soloist.env").read_text() == 'SOLOIST_KEY="abcdef0123456789"\n'
    assert oct((tmp_path / "soloist.env").stat().st_mode & 0o777) == "0o600"
    item = {"uri": "spotify:track:1", "playback": {"duration_ms": 643000},
            "decorations": {"identity": {"name": "Blue Train"},
                            "visual_identity": {"cover": [{"size": "default", "url": "https://i.scdn.co/a"},
                                                          {"size": "large", "url": "https://i.scdn.co/b"}]}},
            "creators": [{"entity": {"decorations": {"identity": {"name": "John Coltrane"}}}}],
            "parent": {"entity": {"decorations": {"identity": {"name": "Blue Train"}}}}}
    m = soloist.track_meta(item, {"position_ms": 61000, "speed": 0})
    assert (m["title"], m["artist"], m["album"], m["duration"], m["image"], m["position"]) == \
        ("Blue Train", "John Coltrane", "Blue Train", 643.0, "https://i.scdn.co/b", 61.0)


async def test_soloist_drives_the_player(client, device):
    """Soloist events start/pause/stop Spotify on the Aroio; buttons go back as commands."""
    from aroiod.soloist import SoloistClient
    sent = []

    class FakeWS:
        closed = False

        async def send_json(self, data):
            sent.append(data)
    c = SoloistClient(device)
    c.ws, c.connected = FakeWS(), True
    item = {"uri": "spotify:track:1", "playback": {"duration_ms": 200000},
            "decorations": {"identity": {"name": "So What"}}}
    await c.handle({"type": "playback_state", "status": "playing", "is_active": True, "item": item,
                    "position": {"position_ms": 0, "speed": 0}})
    p = (await state(client))["player"]
    assert p["source"] == "spotify" and p["state"] == "playing" and p["track"]["title"] == "So What"
    await c.handle({"type": "playback_changed", "status": "paused"})
    assert (await state(client))["player"]["state"] == "paused"
    await c.handle({"type": "playback_changed", "status": "playing"})
    assert (await state(client))["player"]["state"] == "playing"
    await c.command("next")
    await c.command("seek", 30.5)
    assert sent[-2]["command"] == "skip_next" and sent[-1] == {"type": "command", "command": "seek", "position_ms": 30500}
    await c.handle({"type": "device_changed", "is_active": False})
    assert (await state(client))["player"]["state"] == "stopped"


async def test_spotify_events_keep_meta_and_volume(client, device):
    meta = {"id": "spotify:x", "title": "Blue Train", "artist": "John Coltrane", "album": "Blue Train",
            "duration": 643.0, "image": "https://i.scdn.co/image/x", "provider": "spotify", "live": False,
            "format": {"codec": "Vorbis", "bits": 16, "rate": 44100}}
    await post(client, "/internal/source", {"source": "spotify", "event": "meta", "meta": meta})   # before "start"
    await post(client, "/internal/source", {"source": "spotify", "event": "start"})
    p = (await state(client))["player"]
    assert p["source"] == "spotify" and p["track"]["title"] == "Blue Train"
    await post(client, "/internal/source", {"source": "spotify", "event": "volume", "volume": 35})
    assert (await state(client))["player"]["volume"] == 35


def test_headphone_filter_names_and_rates():
    import numpy as np
    from aroiod import dsp, headphones as hp
    from aroiod.sim import sim_headphone_wav
    assert hp.display_name("Headphones_Convolutions/AKG_K701-filters-48k.wav") == "AKG K701"
    assert hp.display_name("Headphones_Convolutions/Sennheiser_momentum_true_wireless 4-filters-48k (2).wav") \
        == "Sennheiser momentum true wireless 4"
    assert hp.display_name("Headphones_Convolutions/SONY_MDR-MV1 -filters-48k.wav") == "SONY MDR-MV1"
    tree = {"tree": [{"path": "README.md", "type": "blob"},
                     {"path": "Headphones_Measurements/AKG_361.csv", "type": "blob"},
                     {"path": "Headphones_Convolutions/b-filters-48k.wav", "type": "blob"},
                     {"path": "Headphones_Convolutions/A-filters-48k.wav", "type": "blob"}]}
    assert [i["name"] for i in hp.parse_tree(tree)[0]["items"]] == ["A", "b"]
    filters, peak = hp.build(sim_headphone_wav("x"))
    _, frames = dsp.read_wav_frames(sim_headphone_wav("x"))
    freqs = np.array([50.0, 1000.0, 5000.0, 15000.0])
    ref = dsp.fir_response_db(frames[:, 0], freqs, 48000)
    for rate, pair in filters.items():
        assert np.max(np.abs(dsp.fir_response_db(pair["L"], freqs, rate) - ref)) < 0.05, rate
        assert np.argmax(np.abs(pair["L"])) < 8            # minimum phase: energy at the start
        assert len(pair["L"]) <= 65536


def test_config_v1_wifi_switch_moves_to_network(tmp_path):
    import json
    from aroiod.config import Config
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"version": 1, "hardware": {"onboard_wifi": False}}))
    c = Config(path)
    assert c.get("network.wifi.enabled") is False and "onboard_wifi" not in c.data["hardware"]
    path.write_text(json.dumps({"version": 1, "hardware": {"onboard_wifi": True}}))
    assert Config(path).get("network.wifi.enabled") is True


async def test_real_wifi_power(monkeypatch, tmp_path):
    from aroiod import real
    calls = []

    async def run(*a):
        calls.append(a)
    monkeypatch.setattr(real, "_run", run)
    monkeypatch.setattr(real, "WIFI_OFF_FLAG", tmp_path / "aroio" / "wifi-off")
    w = real.RealWorld.__new__(real.RealWorld)
    await w.wifi_power(False)
    assert not real.wifi_enabled() and ("systemctl", "stop", "iwd.service") in calls
    await w.hotspot_stop()                       # rescue hotspot over: iwd stays off
    assert ("systemctl", "start", "iwd.service") not in calls
    await w.wifi_power(True)
    assert real.wifi_enabled() and calls[-1] == ("systemctl", "start", "iwd.service")


def test_proxy_address_parsing():
    from aroiod import proxy
    from aroiod.config import Invalid
    assert proxy.parse("http://max:g3h$im@proxy.firma.de:8080") == ("http://proxy.firma.de:8080", "max", "g3h$im")
    assert proxy.parse("proxy.firma.de:3128") == ("http://proxy.firma.de:3128", "", "")
    assert proxy.parse("http://m%40x:p%3Aw@10.0.0.1:8080/") == ("http://10.0.0.1:8080", "m@x", "p:w")
    assert proxy.parse("  ") == ("", "", "")
    for bad in ("https://proxy:8080", "http://proxy", "http://proxy:99999", "http://proxy:80/pfad", "socks5://p:1080"):
        with pytest.raises(Invalid):
            proxy.parse(bad)
    full = proxy.compose("http://proxy.firma.de:8080", "m@x", "p:w$ \"")
    assert full == "http://m%40x:p%3Aw%24%20%22@proxy.firma.de:8080"
    assert proxy.parse(full)[1:] == ("m@x", 'p:w$ "')
    assert proxy.display("http://proxy.firma.de:8080", "max", True) == "http://max:••••@proxy.firma.de:8080"
    env = proxy.env_file(full)
    assert f"https_proxy={full}\n" in env and "NO_PROXY=localhost," in env and '"' not in env and " " not in env
    assert proxy.env_file("") == ""


def test_real_proxy_env(monkeypatch, tmp_path):
    import os
    from aroiod import real
    calls = []

    async def run(*a):
        calls.append(a)
    monkeypatch.setattr(real, "_run", run)
    monkeypatch.setattr(real, "PROXY_ENV", tmp_path / "proxy.env")
    for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "no_proxy", "NO_PROXY"):
        monkeypatch.delenv(k, raising=False)
    w = real.RealWorld.__new__(real.RealWorld)
    w._proxy_write("http://u:p@proxy:8080")
    f = tmp_path / "proxy.env"
    assert f.stat().st_mode & 0o777 == 0o600 and "HTTPS_PROXY=http://u:p@proxy:8080" in f.read_text()
    assert os.environ["https_proxy"] == "http://u:p@proxy:8080"
    w._proxy_write("")
    assert not f.exists() and "https_proxy" not in os.environ


async def test_speaker_check_signal(client, device):
    """One speaker check: tone or pink noise, left/right/both, chosen duration."""
    await post(client, "/system/test-signal", {"kind": "noise", "channel": "R", "seconds": 0.6})
    st = (await state(client))["device"]["test_signal"]
    assert st["kind"] == "noise" and st["channel"] == "R" and st["seconds"] == 0.6
    assert device.world.request["seconds"] == 0.6
    await asyncio.sleep(0.8)
    assert (await state(client))["device"]["test_signal"] is None       # ends by itself
    await post(client, "/system/test-signal", {"kind": "tone", "channel": "L", "seconds": 60})
    await post(client, "/system/test-signal", {"kind": None})
    assert (await state(client))["device"]["test_signal"] is None and device.world.request["kind"] == "signal_stop"
    for bad in ({"kind": "sweep"}, {"kind": "tone", "channel": "M"}, {"kind": "tone", "seconds": 301}):
        await post(client, "/system/test-signal", bad, status=400)


def test_signal_frames_are_seamless():
    from aroiod import real
    import numpy as np
    for kind in ("tone", "noise"):
        raw = b"".join(real.signal_frames(kind, "L", 9.0))
        x = np.frombuffer(raw, "<i4").reshape(-1, 2) / 2147483647
        assert len(x) == 9 * 48000 and not x[:, 1].any()
        assert abs(x[0, 0]) < 1e-3 and abs(x[-1, 0]) < 1e-3                # fades
        jump = np.abs(np.diff(x[191000:193000, 0])).max()                    # block border at 4 s
        typical = np.abs(np.diff(x[100000:120000, 0])).max()
        assert jump <= typical * 1.01
