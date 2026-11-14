"""HTTP API (/api/v1), WebSocket (/api/v1/ws) and the app's static files.

Errors are JSON: {"error": "<text for people>", "field": "<config key>"?}
with 400 (wrong input), 404 (unknown thing) or 409 (not possible right now).
"""

import asyncio
import json
import logging
import re
import time
import zipfile
from io import BytesIO
from pathlib import Path

from aiohttp import WSMsgType, web

from . import dsp
from .config import Invalid
from .library import art_svg
from .migration import FILTER_RE, RATE_TOKENS

log = logging.getLogger("aroiod.web")
routes = web.RouteTableDef()
A = "/api/v1"
DEVICE = web.AppKey("device", object)
WORLD = web.AppKey("world", object)
STARTED = web.AppKey("started", float)


@web.middleware
async def errors(request, handler):
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except Invalid as exc:
        return web.json_response({"error": exc.message, "field": exc.path}, status=400)
    except (KeyError, IndexError, FileNotFoundError) as exc:
        return web.json_response({"error": f"Nicht gefunden: {exc}"}, status=404)
    except (ValueError, dsp.FilterFileError) as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except Exception:  # noqa: BLE001
        log.exception("Unhandled error in %s %s", request.method, request.path)
        return web.json_response({"error": "Interner Fehler. Details stehen im Protokoll."}, status=500)


def dev(request):
    return request.app[DEVICE]


async def body(request):
    if not request.can_read_body:
        return {}
    try:
        data = await request.json()
    except (ValueError, json.JSONDecodeError):
        raise ValueError("Ungültige Anfrage (kein JSON)") from None
    if not isinstance(data, dict):
        raise ValueError("Ungültige Anfrage")
    return data


def ok(data=None):
    return web.json_response(data if data is not None else {"ok": True})


# ── state ────────────────────────────────────────────────────────────────────

@routes.get(A + "/state")
async def get_state(request):
    d = dev(request)
    d.publish_player()  # fresh position
    return ok(d.hub.snapshot())


@routes.get(A + "/ws")
async def websocket(request):
    hub = dev(request).hub
    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)
    dev(request).publish_player()
    await ws.send_json({"type": "snapshot", "state": hub.snapshot()})
    q = hub.subscribe()

    async def pump():
        while True:
            await ws.send_str(await q.get())

    task = asyncio.create_task(pump())
    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT and msg.data == "ping":
                await ws.send_str('{"type":"pong"}')
            elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                break
    finally:
        task.cancel()
        hub.unsubscribe(q)
        sim = request.app.get(WORLD)
        if sim and sim.simulated:
            sim.publish_sim()
    return ws


# ── config ───────────────────────────────────────────────────────────────────

@routes.get(A + "/config")
async def get_config(request):
    return ok(dev(request).config.data)


@routes.patch(A + "/config")
async def patch_config(request):
    return ok(dev(request).patch_config(await body(request)))


# ── player ───────────────────────────────────────────────────────────────────

@routes.post(A + "/player/{action}")
async def player_action(request):
    d, data, action = dev(request), await body(request), request.match_info["action"]
    if action == "play":
        d.play()
    elif action == "pause":
        d.pause()
    elif action == "toggle":
        d.toggle()
    elif action == "stop":
        d.stop()
    elif action == "next":
        d.next()
    elif action == "previous":
        d.previous()
    elif action == "seek":
        d.seek(float(data["position"]))
    elif action == "shuffle":
        d.set_shuffle(data.get("on"))
    elif action == "repeat":
        d.set_repeat(data.get("mode"))
    elif action == "volume":
        d.set_volume(value=data.get("value"), delta=data.get("delta"))
    elif action == "mute":
        d.set_mute(data.get("on"))
    elif action == "source":
        sid = data["source"]
        if sid == "lms":
            d.play()
        else:
            raise ValueError("Diese Quelle startest du in der App auf deinem Handy, z. B. Spotify oder AirPlay.")
    else:
        raise KeyError(action)
    return ok()


@routes.post(A + "/queue")
async def queue_add(request):
    data = await body(request)
    dev(request).play_items(data["id"], data.get("mode", "play"), data.get("start", 0))
    return ok()


@routes.post(A + "/queue/{action}")
async def queue_action(request):
    d, data, action = dev(request), await body(request), request.match_info["action"]
    if action == "jump":
        d.queue_jump(data["index"])
    elif action == "remove":
        d.queue_remove(data["index"])
    elif action == "move":
        d.queue_move(data["from"], data["to"])
    elif action == "clear":
        d.queue_clear()
    else:
        raise KeyError(action)
    return ok()


# ── library ──────────────────────────────────────────────────────────────────

@routes.get(A + "/library/browse")
async def library_browse(request):
    return ok(dev(request).library.browse(request.query.get("path", "")))


@routes.get(A + "/library/search")
async def library_search(request):
    return ok(dev(request).library.search(request.query.get("q", ""), request.query.get("scope", "all")))


@routes.post(A + "/library/favorite")
async def library_favorite(request):
    data = await body(request)
    return ok({"favorite": dev(request).library.toggle_favorite(data["id"])})


@routes.get(A + "/art/{key}.svg")
async def art(request):
    key = request.match_info["key"]
    lib = dev(request).library
    label = ""
    try:
        provider, kind, k = key.split(":", 2)
        if provider in lib.catalogs:
            c = lib.catalogs[provider]
            label = {"album": lambda: c.albums[k]["title"], "artist": lambda: c.artists[k]["name"],
                     "playlist": lambda: c.playlists[k]["title"]}.get(kind, lambda: k)()
        else:
            label = lib.item(key)["title"] if provider == "radio" else k
    except (ValueError, KeyError):
        label = key.split(":")[-1]
    return web.Response(text=art_svg(key, label), content_type="image/svg+xml",
                        headers={"Cache-Control": "public, max-age=86400"})


# ── DSP ──────────────────────────────────────────────────────────────────────

@routes.get(A + "/dsp/presets/{id}/curve")
async def preset_curve(request):
    freqs = dsp.log_freqs(120)
    return ok({"freqs": [round(float(f), 1) for f in freqs],
               "channels": dev(request).preset_curve(request.match_info["id"], freqs)})


@routes.get(A + "/dsp/presets/{id}")
async def preset_get(request):
    pid = request.match_info["id"]
    p = next((x for x in dev(request).config.data["dsp"]["presets"] if x["id"] == pid), None)
    if p is None:
        raise KeyError(pid)
    return ok(p)


@routes.post(A + "/dsp/presets/{id}/activate")
async def preset_activate(request):
    dev(request).patch_config({"dsp": {"active_preset": request.match_info["id"], "enabled": True}})
    return ok()


@routes.patch(A + "/dsp/presets/{id}")
async def preset_patch(request):
    d, data, pid = dev(request), await body(request), request.match_info["id"]
    presets = d.config.data["dsp"]["presets"]
    p = next((x for x in presets if x["id"] == pid), None)
    if p is None:
        raise KeyError(pid)
    if p["origin"] == "builtin":
        raise ValueError("Dieses Preset ist fest eingebaut.")
    allowed = {k: v for k, v in data.items() if k in ("name", "gain_db", "delay_ms", "trim_db", "peq")}
    d.save_preset(dict(p, **allowed), activate=d.config.get("dsp.active_preset") == pid)
    return ok()


@routes.delete(A + "/dsp/presets/{id}")
async def preset_delete(request):
    dev(request).delete_preset(request.match_info["id"])
    return ok()


@routes.post(A + "/dsp/compare")
async def dsp_compare(request):
    dev(request).set_compare((await body(request)).get("bypass"))
    return ok()


@routes.post(A + "/dsp/import")
async def dsp_import(request):
    """multipart: name, files... File names like Acourate: <Name>L96.dbl, or
    field names L_96000 / R_96000."""
    reader = await request.multipart()
    name, files = "Importierter Filter", {}
    while True:
        part = await reader.next()
        if part is None:
            break
        if part.name == "name":
            name = (await part.text()).strip()[:40] or name
            continue
        data = await part.read(decode=False)
        if len(data) > 16 * 1024 * 1024:
            raise ValueError("Datei zu groß (höchstens 16 MB)")
        m = re.fullmatch(r"([LR])_(\d+)", part.name or "")
        if m:
            ch, rate = m[1], int(m[2])
        else:
            fm = FILTER_RE.match(part.filename or "")
            if not fm:
                raise ValueError(f"„{part.filename}“: Kanal und Abtastrate nicht erkennbar "
                                 "(Beispiel: WohnzimmerL96.dbl)")
            ch, rate = fm["ch"], RATE_TOKENS[int(fm["rate"])]
        files[(ch, rate)] = (part.filename or f"{ch}{rate}.dbl", data)
    if not files:
        raise ValueError("Keine Dateien empfangen")
    preset, problems = dev(request).import_fir(name, files)
    return ok({"preset": preset["id"], "warnings": problems})


# ── room correction ──────────────────────────────────────────────────────────

@routes.post(A + "/roomcorr/{action}")
async def roomcorr_action(request):
    await dev(request).wizard.action(request.match_info["action"], await body(request))
    return ok()


# ── services ─────────────────────────────────────────────────────────────────

@routes.post(A + "/services/{provider}/login")
async def service_login(request):
    return ok(dev(request).service_login(request.match_info["provider"], await body(request)))


@routes.post(A + "/services/{provider}/logout")
async def service_logout(request):
    dev(request).service_logout(request.match_info["provider"])
    return ok()


# ── network, bluetooth ───────────────────────────────────────────────────────

@routes.post(A + "/network/scan")
async def network_scan(request):
    return ok({"networks": await dev(request).world.wifi_scan()})


@routes.post(A + "/network/wifi")
async def network_wifi(request):
    d, data = dev(request), await body(request)
    ssid, psk = str(data.get("ssid", "")).strip(), str(data.get("password", ""))
    if not ssid:
        raise Invalid("network.wifi.ssid", "Bitte ein WLAN wählen")
    await d.world.wifi_connect(ssid, psk)
    d.secrets.set("wifi.psk", psk)
    d.patch_config({"network": {"wifi": {"ssid": ssid, "enabled": True}}})
    d.publish_network()
    return ok()


@routes.post(A + "/bluetooth/pairing")
async def bt_pairing(request):
    d = dev(request)
    seconds = int((await body(request)).get("seconds", 120))
    d.world.bt_pairing(max(0, min(seconds, 300)))
    d.publish_bluetooth()
    return ok()


@routes.delete(A + "/bluetooth/devices/{address}")
async def bt_remove(request):
    d = dev(request)
    d.world.bt_remove(request.match_info["address"])
    d.publish_bluetooth()
    return ok()


# ── system ───────────────────────────────────────────────────────────────────

@routes.get(A + "/system")
async def system_info(request):
    d = dev(request)
    return ok({"version": d.update["current"], "model": d.model["label"], "board": d.world.board,
               "uptime": int(time.monotonic() - request.app[STARTED]), "temperature": 47.5,
               "cpu": d.dsp_status.get("load", 0), "memory": {"used": 182, "total": 1024},
               "storage": {"used": 1.2, "total": 29.7}, "simulated": d.world.simulated})


@routes.get(A + "/system/logs")
async def system_logs(request):
    unit = request.query.get("unit", "system")
    now = time.strftime("%b %d %H:%M:%S")
    lines = {
        "system": [f"{now} aroio systemd[1]: Startup finished in 2.1s (kernel) + 3.4s (userspace) = 5.5s.",
                   f"{now} aroio aroiod[312]: ready, audio path up"],
        "audio": [f"{now} aroio camilladsp[290]: Capture started, rate {dev(request).rate}",
                  f"{now} aroio camilladsp[290]: Buffer level OK, no xruns"],
        "lyrion": [f"{now} aroio squeezelite[401]: connected to {dev(request).world.lyrion_external or 'local'}"],
        "kernel": [f"{now} aroio kernel: snd-soc-aroio: registered"],
    }.get(unit)
    if lines is None:
        raise KeyError(unit)
    events = [f"{e['t']} sim: {e['text']}" for e in reversed(dev(request).world.events)]
    return ok({"unit": unit, "lines": lines + (events if unit == "system" else [])})


@routes.get(A + "/system/diagnostics")
async def diagnostics(request):
    d = dev(request)
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        cfg = json.loads(json.dumps(d.config.data))
        z.writestr("config.json", json.dumps(cfg, indent=2, ensure_ascii=False))
        z.writestr("state.json", json.dumps(d.hub.snapshot(), indent=2, ensure_ascii=False, default=str))
        z.writestr("camilladsp.json", json.dumps(getattr(d.world, "camilla", None), indent=2))
    return web.Response(body=buf.getvalue(), content_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="aroio-diagnose-{time.strftime("%Y%m%d-%H%M")}.zip"'})


@routes.post(A + "/system/{action}")
async def system_action(request):
    d, data, action = dev(request), await body(request), request.match_info["action"]
    if action == "update-check":
        await d.check_update()
    elif action == "update-install":
        asyncio.create_task(_safe(d.install_update()))
    elif action == "reboot":
        asyncio.create_task(_safe(d.reboot()))
    elif action == "test-tone":
        d.test_tone(data.get("channel", "both"))
    elif action == "factory-reset":
        if data.get("confirm") != "zuruecksetzen":
            raise ValueError("Bitte bestätigen.")
        d.factory_reset()
    elif action == "setup-complete":
        d.patch_config({"setup": {"completed": True}})
    else:
        raise KeyError(action)
    return ok()


async def _safe(coro):
    try:
        await coro
    except Exception:  # noqa: BLE001
        log.exception("background task failed")


# ── migration ────────────────────────────────────────────────────────────────

@routes.post(A + "/migration/upload")
async def migration_upload(request):
    reader = await request.multipart()
    text, filters = None, {}
    while True:
        part = await reader.next()
        if part is None:
            break
        data = await part.read(decode=False)
        fname = Path(part.filename or part.name or "").name
        if fname.lower().endswith(".zip"):
            with zipfile.ZipFile(BytesIO(data)) as z:
                for info in z.infolist():
                    base = Path(info.filename).name
                    if base == "userconfig.txt":
                        text = z.read(info).decode("utf-8", "replace")
                    elif base.lower().endswith(".dbl") and info.file_size < 16 * 1024 * 1024:
                        filters[base] = z.read(info)
        elif fname == "userconfig.txt" or part.name == "userconfig":
            text = data.decode("utf-8", "replace")
        elif fname.lower().endswith(".dbl"):
            filters[fname] = data
    if not text:
        raise ValueError("Keine userconfig.txt gefunden.")
    dev(request).offer_migration(text, filters, source="Datei")
    return ok()


@routes.post(A + "/migration/{action}")
async def migration_action(request):
    d, action = dev(request), request.match_info["action"]
    if action == "apply":
        d.apply_migration()
    elif action == "finish":
        d.finish_migration()
    elif action == "discard":
        d.pending_migration = None
        d.publish_migration()
    else:
        raise KeyError(action)
    return ok()


# ── simulator ────────────────────────────────────────────────────────────────

@routes.get(A + "/sim/signal/{rid}")
async def sim_signal(request):
    """Samples (float32 LE, 48 kHz) the simulator page plays: sweeps for the room correction."""
    world = request.app[WORLD]
    if not world.simulated:
        raise web.HTTPNotFound()
    data = world.signal(request.match_info["rid"])
    if data is None:
        raise KeyError(request.match_info["rid"])
    return web.Response(body=data, content_type="application/octet-stream", headers={"X-Sample-Rate": "48000"})


@routes.post(A + "/sim/result/{rid}")
async def sim_result(request):
    """Result from the simulator page: JSON (level check) or float32 LE 48 kHz (recording)."""
    world = request.app[WORLD]
    if not world.simulated:
        raise web.HTTPNotFound()
    if request.content_type == "application/json":
        payload = await request.json()
    else:
        payload = await request.read()
        if len(payload) % 4 or len(payload) > 48000 * 4 * 120:
            raise ValueError("Ungültige Aufnahme")
    world.resolve(request.match_info["rid"], payload)
    return ok()


@routes.get(A + "/sim/fir/{name}")
async def sim_fir(request):
    """FIR taps for the simulator page, so it can apply the same filter as CamillaDSP."""
    if not request.app[WORLD].simulated:
        raise web.HTTPNotFound()
    name = request.match_info["name"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", name):
        raise ValueError("Ungültiger Name")
    path = dev(request).data / "filters" / name
    if not path.is_file():
        raise KeyError(name)
    return web.FileResponse(path, headers={"Content-Type": "application/octet-stream"})


@routes.post(A + "/sim/{event}")
async def sim_event(request):
    world = request.app[WORLD]
    if not world.simulated:
        raise web.HTTPNotFound()
    await world.event(request.match_info["event"], await body(request))
    return ok()


# ── app ──────────────────────────────────────────────────────────────────────

def build_app(device, static_dir=None):
    app = web.Application(middlewares=[errors], client_max_size=64 * 1024 * 1024)
    app[DEVICE] = device
    app[WORLD] = device.world
    app[STARTED] = time.monotonic()
    app.add_routes(routes)
    if static_dir and Path(static_dir).is_dir():
        static_dir = Path(static_dir)

        async def spa(request):
            rel = request.match_info.get("tail", "")
            target = (static_dir / rel).resolve()
            if rel and target.is_file() and static_dir.resolve() in target.parents:
                headers = {"Cache-Control": "public, max-age=31536000, immutable"} if "/assets/" in str(target) \
                    else {"Cache-Control": "no-cache"}
                return web.FileResponse(target, headers=headers)
            if rel.startswith("api/"):
                raise web.HTTPNotFound()
            page = "sim.html" if rel.rstrip("/") in ("sim", "dev") and device.world.simulated else "index.html"
            return web.FileResponse(static_dir / page, headers={"Cache-Control": "no-cache"})

        app.router.add_get("/{tail:.*}", spa)
    return app
