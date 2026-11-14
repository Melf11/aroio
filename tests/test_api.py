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
