"""Aroio demo: the simulated device (aroiod --sim) running in the browser (Pyodide).

demo.js hands the app's fetch() calls for /api/v1 to call() and its WebSockets to
open_socket(); everything else is the unchanged aroiod with SimWorld, so the demo
behaves like ./dev.sh. Covers become data: URLs (an <img> cannot reach Python).
"""

import asyncio
import functools
import json
import logging
from unittest import mock
from urllib.parse import quote

from aiohttp import web
from aiohttp.http import HttpVersion, RawRequestMessage
from aiohttp.streams import StreamReader
from aiohttp.web_request import Request
from multidict import CIMultiDict, CIMultiDictProxy
from yarl import URL

from aroiod import library, sim
from aroiod.__main__ import create
from aroiod.web import build_app

logging.basicConfig(level=logging.WARNING, format="%(name)s %(levelname)s %(message)s")
log = logging.getLogger("aroio.demo")

device = None
app = None


_labelling = False


def _art_url(key):
    global _labelling
    label = key.split(":")[-1]
    if device and not _labelling:      # a station's label builds its item, which asks for its cover
        _labelling = True
        try:
            label = library.art_label(device.library, key)
        finally:
            _labelling = False
    return "data:image/svg+xml;charset=utf-8," + quote(library.art_svg(key, label))


library.art_url = _art_url
sim.art_url = _art_url


async def start(data_dir, setup_done=True):
    """Create and start the simulated Aroio (like python -m aroiod --sim)."""
    global device, app
    device = create(data_dir, sim=True, model="AroioLT", board="pi4", mic_mode="sim")
    app = build_app(device)
    if hasattr(device.world, "start"):
        device.world.start()
    device.start()
    device.wizard.publish()
    device.world.publish_sim()
    if setup_done and not device.config.get("setup.completed"):
        device.patch_config({"setup": {"completed": True}})


def _request(method, url, headers, payload):
    """An aiohttp Request without a socket (like aiohttp.test_utils.make_mocked_request,
    which Pyodide's aiohttp does not ship)."""
    hdrs = CIMultiDictProxy(CIMultiDict(headers))
    raw = tuple((k.encode(), v.encode()) for k, v in hdrs.items())
    message = RawRequestMessage(method, url, HttpVersion(1, 1), hdrs, raw, False, None, False, False, URL(url))
    transport = mock.Mock()
    transport.get_extra_info.side_effect = lambda key: ("127.0.0.1", 80) if key in ("sockname", "peername") else None
    protocol = mock.Mock(transport=transport, max_field_size=8190, max_line_length=8190, max_headers=128)
    writer = mock.Mock(transport=transport)
    protocol.writer = writer
    kwargs = {"client_max_size": app._client_max_size}
    return Request(message, payload, protocol, writer, mock.Mock(), asyncio.get_running_loop(), **kwargs)


def _payload(body):
    reader = StreamReader(mock.Mock(_reading_paused=False), 2 ** 16, loop=asyncio.get_running_loop())
    if body:
        reader.feed_data(bytes(body))
    reader.feed_eof()
    return reader


async def call(method, url, content_type=None, body=None):
    """One HTTP request through aroiod's routes and middlewares.
    Returns (status, headers as JSON, body bytes)."""
    if body is not None and hasattr(body, "to_bytes"):      # Uint8Array from the page
        body = body.to_bytes()
    headers = CIMultiDict()
    if content_type:
        headers["Content-Type"] = content_type
    if body:
        headers["Content-Length"] = str(len(body))
    req = _request(method, url, headers, _payload(body))
    match = await app.router.resolve(req)
    match.add_app(app)
    req._match_info = match
    handler = match.handler
    for mw in reversed(app.middlewares):
        handler = functools.partial(mw, handler=handler)
    try:
        resp = await handler(req)
    except web.HTTPException as exc:
        return exc.status, json.dumps({"Content-Type": "application/json"}), \
            json.dumps({"error": exc.text or exc.reason}).encode()
    except Exception as exc:  # noqa: BLE001
        log.exception("demo request %s %s", method, url)
        return 500, json.dumps({"Content-Type": "application/json"}), json.dumps({"error": str(exc)}).encode()
    if isinstance(resp, web.FileResponse):
        data = resp._path.read_bytes()
    else:
        data = resp.body or b""
        if not isinstance(data, (bytes, bytearray)):
            data = getattr(data, "_value", b"")
    out = {k: v for k, v in resp.headers.items()}
    out["Content-Type"] = resp.content_type + (f"; charset={resp.charset}" if resp.charset else "")
    return resp.status, json.dumps(out), bytes(data)


def open_socket(kind, send):
    """Live socket of the app: kind "ws" (state topics) or "levels" (level meter).
    send(text) delivers a message to the page; returns close()."""
    loop = asyncio.get_event_loop()
    if kind == "levels":
        source, queue = device.levels, device.levels.subscribe()
    else:
        device.publish_player()
        send(json.dumps({"type": "snapshot", "state": device.hub.snapshot()}, ensure_ascii=False))
        source, queue = device.hub, device.hub.subscribe()

    async def pump():
        while True:
            send(await queue.get())

    task = loop.create_task(pump())

    def close():
        task.cancel()
        source.unsubscribe(queue)
        if kind == "ws":
            device.world.publish_sim()

    return close
