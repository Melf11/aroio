"""HTTP API (/api/v1), WebSocket (/api/v1/ws) and the app's static files.

Errors are JSON: {"error": "<text for people>", "field": "<config key>"?}
with 400 (wrong input), 404 (unknown thing) or 409 (not possible right now).
"""

import asyncio
import json
import logging
import re
import time
import weakref
import zipfile
from io import BytesIO
from pathlib import Path

from aiohttp import WSMsgType, web

from . import dsp
from .config import Invalid
from .engine import SOURCES
from .library import art_label, art_svg
from .migration import FILTER_RE, RATE_TOKENS
from .store import load_json

log = logging.getLogger("aroiod.web")
routes = web.RouteTableDef()
A = "/api/v1"
DEVICE = web.AppKey("device", object)
WORLD = web.AppKey("world", object)
STARTED = web.AppKey("started", float)
SOCKETS = web.AppKey("sockets", weakref.WeakSet)   # open websockets, closed on shutdown


@web.middleware
async def captive(request, handler):
    """Setup hotspot: send captive portal probes and foreign hosts to the setup page."""
    ns = request.app[DEVICE].netsetup
    if ns and ns.is_foreign_host(request.host, request.path):
        from .netsetup import HOTSPOT_ADDRESS, PORTAL_PATH
        raise web.HTTPFound(f"http://{HOTSPOT_ADDRESS}{PORTAL_PATH}", headers={"Cache-Control": "no-store"})
    return await handler(request)


@web.middleware
async def auth(request, handler):
    """Optional app password: API and live sockets need a session (see auth.py)."""
    a = request.app[DEVICE].auth
    if not a.allowed(request):
        return web.json_response({"error": "Bitte anmelden.", "login": True}, status=401)
    return await handler(request)


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
    request.app[SOCKETS].add(ws)
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


@routes.get(A + "/levels")
async def levels_ws(request):
    """Live levels for the meter: {"peak": [L, R], "rms": [L, R]} in dBFS, about 15 per second."""
    lv = dev(request).levels
    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)
    request.app[SOCKETS].add(ws)
    q = lv.subscribe()

    async def pump():
        while True:
            await ws.send_str(await q.get())

    task = asyncio.create_task(pump())
    try:
        async for msg in ws:
            if msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                break
    finally:
        task.cancel()
        lv.unsubscribe(q)
    return ws


# ── app password ──

@routes.get(A + "/auth/status")
async def auth_status(request):
    a = dev(request).auth
    from .auth import COOKIE
    return ok({"enabled": a.enabled, "logged_in": (not a.enabled) or a.valid(request.cookies.get(COOKIE))})


def _session_cookie(resp, token):
    from .auth import COOKIE
    resp.set_cookie(COOKIE, token, max_age=365 * 86400, httponly=True, samesite="Lax", path="/")


@routes.post(A + "/auth/login")
async def auth_login(request):
    a, data = dev(request).auth, await body(request)
    if not a.enabled:
        return ok()
    if not a.check(str(data.get("password", ""))):
        await asyncio.sleep(1.0)                 # slow down guessing
        raise ValueError("Das Passwort stimmt nicht.")
    resp = ok()
    _session_cookie(resp, a.new_session())
    return resp


@routes.post(A + "/auth/logout")
async def auth_logout(request):
    from .auth import COOKIE
    dev(request).auth.end_session(request.cookies.get(COOKIE))
    resp = ok()
    resp.del_cookie(COOKIE, path="/")
    return resp


@routes.post(A + "/security/password")
async def set_app_password(request):
    """{"password": "..."} sets it (and logs this browser in), {"password": null} turns it off."""
    token = dev(request).auth.set_password((await body(request)).get("password"))
    resp = ok()
    if token:
        _session_cookie(resp, token)
    return resp


@routes.get(A + "/internal/status")
async def internal_status(request):
    """For the info screen on the device (localhost only, no password)."""
    if request.remote not in ("127.0.0.1", "::1"):
        raise web.HTTPForbidden()
    d = dev(request)
    if "wait" in request.query:
        # the screen waits here for a key of the TV remote (at most 1 s): menu without delay
        try:
            await d.tvmenu.wait(int(request.query["wait"]), 1.0)
        except ValueError:
            pass
    s = d.hub.snapshot()
    p, n = s.get("player") or {}, s.get("network") or {}
    t = p.get("track") or {}
    sig = p.get("signal") or {}
    fmt = dict(t.get("format") or {})
    fmt.setdefault("rate", sig.get("rate_out"))
    return ok({"name": d.config.get("device.name"), "hostname": d.config.get("network.hostname"),
               "lan": (n.get("lan") or {}).get("address"), "wifi": (n.get("wifi") or {}).get("address"),
               "hotspot": (n.get("hotspot") or {}).get("ssid") if (n.get("hotspot") or {}).get("active") else None,
               "state": p.get("state"), "source": p.get("source_name"),
               "title": t.get("title"), "artist": t.get("artist"), "album": t.get("album"),
               "cover_id": t.get("image"), "duration": t.get("duration") or None,
               "position": round(d.position(), 1), "format": fmt,
               "preset": sig.get("preset") if sig.get("processing") else None,
               "volume": p.get("volume"), "muted": p.get("muted"), "fixed_level": d.fixed_level,
               "rotate": d.config.get("hardware.display_rotate"),
               "menu": d.tvmenu.state(),
               "rate": sig.get("rate_out")})


@routes.get(A + "/internal/cover")
async def internal_cover(request):
    """The current cover for the info screen (localhost only): aroiod fetches covers from
    the internet itself (proxy, company certificate), the screen only talks to aroiod."""
    if request.remote not in ("127.0.0.1", "::1"):
        raise web.HTTPForbidden()
    d = dev(request)
    url = ((d.hub.snapshot().get("player") or {}).get("track") or {}).get("image")
    if not url:
        raise web.HTTPNotFound()
    if url.startswith("/"):
        raise web.HTTPFound(url)                 # served by aroiod itself (AirPlay, library)
    cached = getattr(d, "_cover_cache", None)
    if not cached or cached[0] != url:
        try:
            data = await d.world.fetch(url, 4 * 1024 * 1024)
        except ValueError:
            raise web.HTTPNotFound() from None
        cached = d._cover_cache = (url, data)
    return web.Response(body=cached[1], content_type="image/jpeg")


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
    return web.Response(text=art_svg(key, art_label(dev(request).library, key)), content_type="image/svg+xml",
                        headers={"Cache-Control": "public, max-age=86400"})


# ── DSP ──────────────────────────────────────────────────────────────────────

@routes.get(A + "/audio/hardware")
async def audio_hardware(request):
    return ok(dev(request).audio_hardware())


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


@routes.get(A + "/dsp/presets/{id}/measurement")
async def preset_measurement(request):
    """The room measurement a preset was calculated from (for the filter editor)."""
    d, pid = dev(request), request.match_info["id"]
    p = next((x for x in d.config.data["dsp"]["presets"] if x["id"] == pid), None)
    if p is None or not p.get("measurement"):
        raise KeyError(pid)
    data = load_json(d.data / "measurements" / f"{p['measurement']}.json", None)
    if data is None:
        raise KeyError(pid)
    return ok(data)


@routes.post(A + "/dsp/presets")
async def preset_create(request):
    """New own equalizer (no measuring microphone needed)."""
    data = await body(request)
    return ok(dev(request).create_eq((data or {}).get("name")))


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
    if "peq" in allowed and p["kind"] != "peq":
        raise ValueError("Nur Equalizer-Einstellungen haben bearbeitbare Filter.")
    if "peq" in allowed and "gain_db" not in allowed:
        try:   # automatic headroom: never clip because of a boost
            allowed["gain_db"] = dsp.headroom_db(allowed["peq"])
        except (KeyError, TypeError, ValueError):
            pass   # invalid filters: the config validation reports them
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
    field names L_96000 / R_96000, or a single stereo WAV (converted for every rate)."""
    reader = await request.multipart()
    name, given, files, stereo = "Importierter Filter", "", {}, []
    while True:
        part = await reader.next()
        if part is None:
            break
        if part.name == "name":
            given = (await part.text()).strip()[:40]
            name = given or name
            continue
        data = await part.read(decode=False)
        if len(data) > 16 * 1024 * 1024:
            raise ValueError("Datei zu groß (höchstens 16 MB)")
        m = re.fullmatch(r"([LR])_(\d+)", part.name or "")
        fm = FILTER_RE.match(part.filename or "")
        if m:
            ch, rate = m[1], int(m[2])
        elif fm:
            ch, rate = fm["ch"], RATE_TOKENS[int(fm["rate"])]
        else:
            stereo.append((part.filename or "filter.wav", data))
            continue
        files[(ch, rate)] = (part.filename or f"{ch}{rate}.dbl", data)
    if stereo:
        # one stereo WAV (e.g. from the headphone project): left and right in one file
        if files or len(stereo) > 1:
            raise ValueError("Eine Stereo-WAV bitte allein hochladen, ohne weitere Dateien.")
        preset = await dev(request).import_stereo_wav(given, *stereo[0])
        return ok({"preset": preset["id"], "warnings": []})
    if not files:
        raise ValueError("Keine Dateien empfangen")
    preset, problems = dev(request).import_fir(name, files)
    return ok({"preset": preset["id"], "warnings": problems})


@routes.get(A + "/dsp/headphones")
async def dsp_headphones(request):
    """Models of the headphone correction project (downloaded from GitHub, cached)."""
    return ok(await dev(request).headphone_list())


@routes.post(A + "/dsp/headphones")
async def dsp_headphones_apply(request):
    data = await body(request)
    preset = await dev(request).apply_headphone_filter(str(data.get("path", "")))
    return ok({"preset": preset["id"], "name": preset["name"]})


# ── room correction ──────────────────────────────────────────────────────────

@routes.get(A + "/roomcorr/recordings.zip")
async def roomcorr_recordings(request):
    last = dev(request).data / "measurements" / "last"
    if not (last / "info.txt").exists():
        raise KeyError("Noch keine Messung")
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(last.iterdir()):
            z.write(f, f.name)
    return web.Response(body=buf.getvalue(), content_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="aroio-messung-{time.strftime("%Y%m%d-%H%M")}.zip"'})


@routes.post(A + "/roomcorr/{action}")
async def roomcorr_action(request):
    await dev(request).wizard.action(request.match_info["action"], await body(request))
    return ok()


# ── services ─────────────────────────────────────────────────────────────────

@routes.post(A + "/services/lyrion/credentials")
async def lyrion_credentials(request):
    data = await body(request)
    dev(request).set_lyrion_credentials(data.get("user"), data.get("password"))
    return ok()


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
    return ok({"networks": await dev(request).netsetup.scan()})


@routes.post(A + "/network/wifi")
async def network_wifi(request):
    d, data = dev(request), await body(request)
    ssid, psk = str(data.get("ssid", "")).strip(), str(data.get("password", ""))
    if not ssid:
        raise Invalid("network.wifi.ssid", "Bitte ein WLAN wählen")
    result = await d.netsetup.connect(ssid, psk)
    d.publish_network()
    return ok(result)


@routes.post(A + "/network/proxy")
async def network_proxy(request):
    """{"url": "http://user:pass@proxy:port"} sets the proxy, "" removes it."""
    d, data = dev(request), await body(request)
    d.set_proxy(str(data.get("url", "")))
    return ok({"proxy": d.hub.snapshot()["network"]["proxy"]})


@routes.post(A + "/network/proxy-ca")
async def network_proxy_ca(request):
    """multipart "file": the company's root certificate (PEM or DER) for TLS-inspecting proxies."""
    reader = await request.multipart()
    data = None
    while (part := await reader.next()) is not None:
        if part.name == "file":
            data = await part.read(decode=False)
    if not data or len(data) > 512 * 1024:
        raise ValueError("Bitte eine Zertifikatsdatei wählen (höchstens 512 KB).")
    d = dev(request)
    d.set_proxy_ca(data)
    return ok({"proxy": d.hub.snapshot()["network"]["proxy"]})


@routes.delete(A + "/network/proxy-ca")
async def network_proxy_ca_delete(request):
    d = dev(request)
    d.set_proxy_ca(None)
    return ok({"proxy": d.hub.snapshot()["network"]["proxy"]})


@routes.post(A + "/network/internet-test")
async def network_internet_test(request):
    await dev(request).internet_test()
    return ok()


@routes.post(A + "/bluetooth/pairing")
async def bt_pairing(request):
    d = dev(request)
    seconds = int((await body(request)).get("seconds", 120))
    d.world.bt_pairing(max(0, min(seconds, 300)))
    d.publish_bluetooth()
    return ok()


@routes.delete(A + "/bluetooth/devices")
async def bt_remove_all(request):
    d = dev(request)
    d.world.bt_remove_all()
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


@routes.get(A + "/cover/{provider}")
async def cover(request):
    """Cover art that only exists on the device (AirPlay sends it with the stream)."""
    getter = getattr(dev(request).world, "cover", None)
    art = getter(request.match_info["provider"]) if getter else None
    if not art:
        raise web.HTTPNotFound()
    kind, data = art
    return web.Response(body=data, content_type=kind, headers={"Cache-Control": "max-age=86400"})


@routes.get(A + "/system/licenses")
async def licenses(request):
    return ok({"components": dev(request).world.licenses()})


@routes.get(A + "/hardware/ir")
async def ir_get(request):
    d = dev(request)
    from .models import IR_ACTIONS
    return ok({"map": d.config.get("hardware.ir_map"), "last": d.last_ir, "actions": IR_ACTIONS,
               "enabled": d.config.get("hardware.ir_enabled")})


@routes.post(A + "/hardware/ir/learn")
async def ir_learn(request):
    code = await dev(request).learn_ir((await body(request)).get("action"))
    return ok({"code": code})


@routes.post(A + "/hardware/ir/reset")
async def ir_reset(request):
    from .models import DEFAULT_IR_MAP
    dev(request).patch_config({"hardware": {"ir_map": dict(DEFAULT_IR_MAP)}})
    return ok()


@routes.get(A + "/system/logs")
async def system_logs(request):
    unit = request.query.get("unit", "system")
    lines = await asyncio.get_event_loop().run_in_executor(None, dev(request).world.logs, unit)
    return ok({"unit": unit, "lines": lines})


@routes.get(A + "/system/diagnostics")
async def diagnostics(request):
    d = dev(request)
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        cfg = json.loads(json.dumps(d.config.data))
        z.writestr("config.json", json.dumps(cfg, indent=2, ensure_ascii=False))
        z.writestr("state.json", json.dumps(d.hub.snapshot(), indent=2, ensure_ascii=False, default=str))
        cam = getattr(d.world, "camilla", None)
        z.writestr("camilladsp.json", json.dumps(cam if isinstance(cam, dict) else getattr(cam, "config", None), indent=2))
        extra = getattr(d.world, "diagnostics_files", None)
        if extra:
            for name, text in (await asyncio.get_event_loop().run_in_executor(None, extra)).items():
                z.writestr(name, text)
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
    elif action == "test-noise":
        d.test_noise(data.get("channel"))
    elif action == "test-signal":
        d.test_signal(data.get("kind"), data.get("channel", "both"), data.get("seconds", 2))
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


@routes.post(A + "/internal/source")
async def internal_source(request):
    """Events from player hooks on the device (shairport-sync, squeezelite ...):
    {"source": "airplay", "event": "start"|"stop"|"meta", "meta": {...}, "rate": 44100}.
    Only from the device itself."""
    if request.remote not in ("127.0.0.1", "::1"):
        raise web.HTTPForbidden()
    d, data = dev(request), await body(request)
    sid, event = data.get("source"), data.get("event")
    if sid not in ("lms", "spotify", "airplay", "upnp", "bluetooth", "input", "roon", "netjack"):
        raise ValueError("Unbekannte Quelle")
    meta = data.get("meta") or d.source_meta.get(sid) or {
        "title": SOURCES[sid]["name"], "artist": "", "album": "", "duration": 0, "live": True,
        "format": {"codec": "PCM", "bits": 0, "rate": data.get("rate") or 44100}}
    if event == "start":
        d.source_started(sid, meta, rate=data.get("rate"))
    elif event == "stop":
        d.source_stopped(sid)
    elif event == "meta":
        d.external_meta(sid, meta)
    elif event == "volume":
        if d.source == sid:
            d.remote_volume(float(data.get("volume", 0)))
    else:
        raise ValueError("Unbekanntes Ereignis")
    return ok()


@routes.post(A + "/sim/{event}")
async def sim_event(request):
    world = request.app[WORLD]
    if not world.simulated:
        raise web.HTTPNotFound()
    await world.event(request.match_info["event"], await body(request))
    return ok()


# ── app ──────────────────────────────────────────────────────────────────────

def build_app(device, static_dir=None):
    app = web.Application(middlewares=[captive, auth, errors], client_max_size=64 * 1024 * 1024)
    app[DEVICE] = device
    app[WORLD] = device.world
    app[STARTED] = time.monotonic()
    app[SOCKETS] = weakref.WeakSet()

    async def close_sockets(app):
        # otherwise a stop waits for every open app (systemctl restart took ~15-30 s)
        for ws in list(app[SOCKETS]):
            await ws.close(code=1001, message=b"restart")

    app.on_shutdown.append(close_sockets)
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
            if rel.startswith("api/") or "." in rel.rsplit("/", 1)[-1]:
                raise web.HTTPNotFound()      # a missing file is a 404, not the app page
            page = "sim.html" if rel.rstrip("/") in ("sim", "dev") and device.world.simulated else "index.html"
            return web.FileResponse(static_dir / page, headers={"Cache-Control": "no-cache"})

        app.router.add_get("/{tail:.*}", spa)
    return app
