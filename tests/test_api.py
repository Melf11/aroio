import asyncio

import aiohttp
import pytest


async def state(client):
    r = await client.get("/api/v1/state")
    assert r.status == 200
    return await r.json()


async def post(client, path, data=None, status=200):
    r = await client.post("/api/v1" + path, json=data or {})
    body = await r.json()
    assert r.status == status, body
    return body


async def test_play_album_follows_rate(client, device):
    page = await (await client.get("/api/v1/library/browse", params={"path": "local/albums"})).json()
    album = next(i for i in page["items"] if "96" in i["quality"] or "192" in i["quality"])
    await post(client, "/queue", {"id": album["id"]})
    s = await state(client)
    assert s["player"]["state"] == "playing" and s["player"]["source"] == "lms"
    rate = s["player"]["track"]["format"]["rate"]
    assert s["player"]["signal"]["rate_in"] == rate == s["player"]["signal"]["rate_out"]
    assert device.world.camilla["devices"]["samplerate"] == rate
    assert len(s["queue"]["items"]) > 1 and s["queue"]["index"] == 0
    await post(client, "/player/next")
    assert (await state(client))["queue"]["index"] == 1


async def test_external_source_pauses_lms(client, device):
    await post(client, "/queue", {"id": "local:album:1"})
    await post(client, "/sim/external_start", {"source": "airplay"})
    s = await state(client)
    assert s["player"]["source"] == "airplay"
    assert s["player"]["signal"]["rate_in"] == 44100
    assert any("angehalten" in e["text"] for e in device.world.events)
    await post(client, "/sim/external_stop", {"source": "airplay"})
    assert (await state(client))["player"]["state"] == "stopped"


async def test_disabled_source_is_ignored(client):
    await client.patch("/api/v1/config", json={"sources": {"spotify": {"enabled": False}}})
    await post(client, "/sim/external_start", {"source": "spotify"})
    assert (await state(client))["player"]["source"] != "spotify"


async def test_volume_encoder_and_fixed_level(client, device):
    await post(client, "/player/volume", {"value": 50})
    await post(client, "/sim/encoder", {"steps": 2})
    assert (await state(client))["player"]["volume"] == 54
    await post(client, "/sim/model", {"model": "AroioEX"})
    body = await post(client, "/player/volume", {"value": 10}, status=400)
    assert "festen Ausgangspegel" in body["error"]
    assert (await state(client))["player"]["volume"] is None


async def test_config_error_names_field(client):
    r = await client.patch("/api/v1/config", json={"network": {"hostname": "nicht ok"}})
    assert r.status == 400
    assert (await r.json())["field"] == "network.hostname"


async def test_websocket_snapshot_and_updates(client):
    ws = await client.ws_connect("/api/v1/ws")
    snap = await ws.receive_json()
    assert snap["type"] == "snapshot" and "player" in snap["state"]
    await post(client, "/player/volume", {"value": 20})
    for _ in range(10):
        msg = await asyncio.wait_for(ws.receive_json(), 2)
        if msg.get("topic") == "player":
            assert msg["data"]["volume"] == 20
            break
    else:
        pytest.fail("no player update")
    await ws.close()


async def test_ir_key_switches_preset(client, device):
    device.save_preset({"id": "p2", "name": "Zwei", "kind": "peq", "peq": {"L": [], "R": []}}, activate=False)
    await post(client, "/sim/key", {"key": "KEY_2"})
    assert device.config.get("dsp.active_preset") == "p2"


async def test_migration_end_to_end(client, device):
    await post(client, "/sim/old_device")
    s = await state(client)
    assert s["migration"]["pending"] and s["migration"]["report"]
    await post(client, "/migration/apply")
    assert device.config.get("device.name") == "Aroio Wohnzimmer"
    assert device.config.get("dsp.active_preset") == "bank0"
    assert (device.data / "filters" / "bank0_L_96000.dbl").exists()
    assert device.secrets.get("wifi.psk") is None
    await post(client, "/migration/finish")
    s = await state(client)
    assert not s["migration"]["pending"] and s["device"]["setup_completed"]
    # music at 88.2 kHz has no filter: nearest rate of the same family (44.1k) is used
    device.set_rate(88200)
    assert device.dsp_status["rate_out"] == 44100 and device.dsp_status["note"] == "missing_rate"


async def test_fir_import(client, device):
    import numpy as np
    taps = np.zeros(1024)
    taps[10] = 1.0
    form = aiohttp.FormData()
    form.add_field("name", "Acourate Test")
    for ch in "LR":
        form.add_field("file", taps.astype("<f8").tobytes(), filename=f"RaumX{ch}96.dbl")
    r = await client.post("/api/v1/dsp/import", data=form)
    body = await r.json()
    assert r.status == 200, body
    pid = body["preset"]
    await post(client, f"/dsp/presets/{pid}/activate")
    device.set_rate(96000)
    assert device.dsp_status["fir_taps"] == 1024
    curve = await (await client.get(f"/api/v1/dsp/presets/{pid}/curve")).json()
    assert abs(curve["channels"]["L"][50]) < 0.1


async def test_roomcorr_wizard_full_flow(client, device):
    rc = lambda a, d=None, status=200: post(client, "/roomcorr/" + a, d, status)  # noqa: E731
    await rc("start")
    await rc("next")
    body = await rc("next", status=400)
    assert "mikrofon" in body["error"].lower()
    await post(client, "/sim/mic", {"on": True})
    await rc("next")
    await rc("next")
    await rc("level")
    await rc("next")
    await rc("set_positions", {"count": 2})
    await post(client, "/sim/noise_next")
    await rc("measure")
    s = (await state(client))["roomcorr"]
    assert s["issue"]["kind"] == "noise" and not s["measured"]
    for _ in range(2):
        await rc("measure")
    await rc("next")
    await rc("set_character", {"character": "warm"})
    await rc("compute")
    s = (await state(client))["roomcorr"]
    assert s["step"] == "result" and s["comparing"]
    assert device.config.get("dsp.active_preset") == "preview"
    await rc("listen", {"which": "old"})
    assert device.config.get("dsp.active_preset") == "bypass"
    await rc("save", {"name": "Wohnzimmer"})
    active = device.config.get("dsp.active_preset")
    assert active.startswith("rc-")
    assert "preview" not in [p["id"] for p in device.config.get("dsp.presets")]
    assert device.config.get("dsp.character") == "warm"


async def test_update_and_reboot(client, device):
    await post(client, "/system/update-check")
    s = await state(client)
    assert s["update"]["available"] == "0.2.0"
    await device.install_update()
    assert device.update["state"] == "reboot_required"
    await device.reboot()
    assert device.update["current"] == "0.2.0"


async def test_services_login(client, device):
    body = await post(client, "/services/tidal/login", {"action": "start"})
    assert len(body["code"]) == 5
    await post(client, "/sim/tidal_confirm")
    s = await state(client)
    assert s["services"]["tidal"]["logged_in"]
    await post(client, "/services/qobuz/login", {"email": "x", "password": "y"}, status=400)
    await client.patch("/api/v1/config", json={"services": {"tidal": {"enabled": True}}})
    page = await (await client.get("/api/v1/library/browse", params={"path": "tidal"})).json()
    assert page["items"]
    word = device.library.catalogs["local"].albums["0"]["title"].split()[0]
    res = await (await client.get("/api/v1/library/search", params={"q": word})).json()
    assert {g["provider"] for g in res["groups"]} >= {"local", "tidal"}


async def test_host_microphone_roundtrip(client, device):
    """Real microphone in the simulator browser: aroiod asks the page to play +
    record; here the test plays the page's part with the simulated room."""
    import numpy as np
    from aroiod import roomcorr

    world = device.world
    await post(client, "/sim/mic_mode", {"mode": "host", "label": "UMIK-1 Test"})

    async def browser():
        done = set()
        room = roomcorr.SimRoom(48000)
        while True:
            await asyncio.sleep(0.02)
            req = (await state(client))["sim"]["request"]
            if not req or req["id"] in done:
                continue
            done.add(req["id"])
            if req["kind"] == "level":
                await client.post(f"/api/v1/sim/result/{req['id']}", json={"rms_dbfs": -28.0, "gain_db": -20})
            elif req["kind"] == "measure":
                raw = await (await client.get(f"/api/v1/sim/signal/{req['id']}")).read()
                sweep = np.frombuffer(raw, dtype="<f4").astype(np.float64)
                rec = room.record(sweep, req["channel"], 0).astype("<f4").tobytes()
                await client.post(f"/api/v1/sim/result/{req['id']}", data=rec,
                                  headers={"Content-Type": "application/octet-stream"})

    task = asyncio.create_task(browser())
    try:
        rc = lambda a, d=None: post(client, "/roomcorr/" + a, d)  # noqa: E731
        await rc("start")
        await rc("next")
        s = (await state(client))["roomcorr"]
        assert s["mic"]["connected"] and "am Rechner" in s["mic"]["name"]
        await rc("next")
        await rc("next")
        await rc("level")
        s = (await state(client))["roomcorr"]
        assert s["level"]["status"] == "ok" and s["level"]["unit"] == "dBFS"
        await rc("next")
        await rc("set_positions", {"count": 1})
        await rc("measure")
        assert len((await state(client))["roomcorr"]["measured"]) == 2
    finally:
        task.cancel()


async def test_host_microphone_timeout_message(client, device):
    device.world.mic_mode, device.world.host_mic, device.world.host_timeout = "host", "Mic", 0.05
    gen = device.world.level_check()
    await gen.__anext__()
    with pytest.raises(ValueError, match="Simulator hat nicht geantwortet"):
        await gen.__anext__()


async def test_audio_hardware_output_and_driver(client, device):
    hw = await (await client.get("/api/v1/audio/hardware")).json()
    assert [o["kind"] for o in hw["outputs"]] == ["hat", "hdmi"]           # AroioLT: Aroio DAC + HDMI, no loopback/mic
    assert hw["active"] == "hw:CARD=AroioDAC,DEV=0" and hw["selected"] == "auto"
    assert any(d["id"] == "rpi-dacplus" for d in hw["drivers"])

    # plug in a USB DAC and choose it: CamillaDSP plays there
    await post(client, "/sim/usb_dac", {"on": True})
    await client.patch("/api/v1/config", json={"audio": {"output": "hw:CARD=DragonFly,DEV=0"}})
    assert device.world.camilla["devices"]["playback"]["device"] == "hw:CARD=DragonFly,DEV=0"
    # unplugged: falls back to the automatic choice instead of failing
    await post(client, "/sim/usb_dac", {"on": False})
    assert device.world.camilla["devices"]["playback"]["device"] == "hw:CARD=AroioDAC,DEV=0"

    # driver change: written to the boot partition, active after reboot
    await client.patch("/api/v1/config", json={"hardware": {"dac_driver": "onboard"}})
    s = await state(client)
    assert s["device"]["reboot_required"] is True
    assert "AroioDAC" in device.world.dac_device                         # not yet
    await device.reboot()
    assert (await state(client))["device"]["reboot_required"] is False
    kinds = [o["kind"] for o in (await (await client.get("/api/v1/audio/hardware")).json())["outputs"]]
    assert kinds == ["analog", "hdmi"]
    r = await client.patch("/api/v1/config", json={"hardware": {"dac_driver": "nope"}})
    assert r.status == 400


async def run_wizard_to_result(client, positions=1):
    rc = lambda a, d=None: post(client, "/roomcorr/" + a, d)  # noqa: E731
    await post(client, "/sim/mic", {"on": True})
    for a in ("start", "next", "next", "next", "level", "next"):
        await rc(a)
    await rc("set_positions", {"count": positions})
    for _ in range(positions):
        await rc("measure")
    await rc("next")
    await rc("compute")
    return rc


async def test_manual_filters_in_wizard(client, device):
    rc = await run_wizard_to_result(client)
    r = (await state(client))["roomcorr"]["result"]
    auto_l = r["channels"]["L"]["filters"]
    # add a 4 dB boost at 80 Hz to the left channel: preview follows, headroom protects
    await rc("set_filters", {"channel": "L", "filters": auto_l + [{"type": "peaking", "freq": 80, "gain": 4, "q": 1}]})
    r = (await state(client))["roomcorr"]["result"]
    assert r["channels"]["L"]["manual"] is True and r["channels"]["R"].get("manual") is not True
    preview = next(p for p in device.config.get("dsp.presets") if p["id"] == "preview")
    assert len(preview["peq"]["L"]) == len(auto_l) + 1
    assert r["headroom_db"] <= -3.5
    # invalid values are rejected with a readable message
    body = await post(client, "/roomcorr/set_filters", {"channel": "both", "filters": [{"type": "peaking", "freq": 5, "gain": 0, "q": 1}]}, status=400)
    assert "mindestens" in body["error"]
    await rc("reset_filters")
    assert (await state(client))["roomcorr"]["result"]["channels"]["L"]["filters"] == auto_l
    # both channels at once, then save: the measurement is kept for later editing
    await rc("set_filters", {"channel": "both", "filters": [{"type": "peaking", "freq": 43, "gain": -6, "q": 3}]})
    await rc("save", {"name": "Von Hand"})
    pid = device.config.get("dsp.active_preset")
    m = await (await client.get(f"/api/v1/dsp/presets/{pid}/measurement")).json()
    assert len(m["freqs"]) == len(m["channels"]["L"]["before"]) and m["channels"]["R"]["auto_filters"]


async def test_edit_peq_preset_headroom(client, device):
    device.save_preset({"id": "eq1", "name": "EQ", "kind": "peq", "peq": {"L": [], "R": []}}, activate=True)
    r = await client.patch("/api/v1/dsp/presets/eq1", json={"peq": {"L": [{"type": "lowshelf", "freq": 100, "gain": 5, "q": 0.7}], "R": []}})
    assert r.status == 200
    p = next(x for x in device.config.get("dsp.presets") if x["id"] == "eq1")
    assert p["gain_db"] <= -4.5 and len(p["peq"]["L"]) == 1
    assert "peq_L_0" in device.world.camilla["filters"]                 # active preset: audible at once
    r = await client.patch("/api/v1/dsp/presets/eq1", json={"peq": {"L": [{"type": "peaking", "freq": 100, "gain": 40, "q": 1}], "R": []}})
    assert r.status == 400
    r = await client.get("/api/v1/dsp/presets/eq1/measurement")
    assert r.status == 404


async def test_setup_hotspot_captive_portal_and_wifi(client, device):
    net = lambda s: s["network"]  # noqa: E731
    await post(client, "/sim/first_boot", {"lan": False})          # no cable, no WLAN
    for _ in range(40):
        await asyncio.sleep(0.1)
        if net(await state(client))["hotspot"]["active"]:
            break
    n = net(await state(client))
    assert n["hotspot"]["ssid"] == "Aroio-Einrichtung-3F2A" and n["networks"]
    assert n["hotspot"]["portal"] == "http://192.168.4.1/einrichtung"

    # captive portal: probes and foreign hosts go to the setup page, the app itself does not
    r = await client.get("/hotspot-detect.html", headers={"Host": "captive.apple.com"}, allow_redirects=False)
    assert r.status == 302 and r.headers["Location"] == "http://192.168.4.1/einrichtung"
    r = await client.get("/generate_204", headers={"Host": "connectivitycheck.gstatic.com"}, allow_redirects=False)
    assert r.status == 302
    r = await client.get("/api/v1/state", headers={"Host": "192.168.4.1"}, allow_redirects=False)
    assert r.status == 200

    # wrong password: hotspot comes back with the reason
    body = await post(client, "/network/wifi", {"ssid": "Zuhause", "password": "kurz"})
    assert body["switching"] is True
    for _ in range(40):
        await asyncio.sleep(0.1)
        n = net(await state(client))
        if n["setup"]["state"] == "failed" and n["hotspot"]["active"]:
            break
    assert n["setup"]["error"] == "Das WLAN-Passwort ist falsch."

    # right password: connected, hotspot stays off, credentials kept
    await post(client, "/network/wifi", {"ssid": "Zuhause", "password": "geheim1234"})
    for _ in range(40):
        await asyncio.sleep(0.1)
        n = net(await state(client))
        if n["setup"]["state"] == "connected":
            break
    assert not n["hotspot"]["active"] and n["wifi"]["connected"]
    assert device.config.get("network.wifi.ssid") == "Zuhause" and device.secrets.get("wifi.psk") == "geheim1234"
    r = await client.get("/hotspot-detect.html", headers={"Host": "captive.apple.com"}, allow_redirects=False)
    assert r.status != 302


async def test_setup_hotspot_stops_with_cable(client, device):
    await post(client, "/sim/first_boot", {"lan": False})
    for _ in range(40):
        await asyncio.sleep(0.1)
        if (await state(client))["network"]["hotspot"]["active"]:
            break
    await post(client, "/sim/lan", {"on": True})
    for _ in range(40):
        await asyncio.sleep(0.1)
        if not (await state(client))["network"]["hotspot"]["active"]:
            break
    assert not (await state(client))["network"]["hotspot"]["active"]
