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
    assert device.world.request["kind"] == "noise_loop"
    await post(client, "/system/test-noise", {"channel": None})
    assert device.world.request["kind"] == "noise_stop"
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
