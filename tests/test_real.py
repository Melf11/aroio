"""Hardware layer without hardware: ALSA parsing, CamillaDSP protocol, player hooks."""

import asyncio
import json

import numpy as np
from aiohttp import WSMsgType, web

from aroiod import real

CARDS = """\
 0 [Loopback       ]: Loopback - Loopback
                      Loopback 1
 1 [vc4hdmi0       ]: vc4-hdmi - vc4-hdmi-0
                      vc4-hdmi-0
 2 [IQaudIODAC     ]: IQaudIODAC - IQaudIODAC
                      IQaudIODAC
 3 [U18dB          ]: USB-Audio - Umik-1  Gain: 18dB
                      miniDSP Umik-1  Gain: 18dB at usb-0000:01:00.0-1.3, full speed
"""


def test_cards_dac_and_mic():
    cards = real.parse_cards(CARDS)
    assert [c["id"] for c in cards] == ["Loopback", "vc4hdmi0", "IQaudIODAC", "U18dB"]
    assert real.find_dac(cards) == "hw:CARD=IQaudIODAC,DEV=0"
    assert real.find_dac(cards, "hw:CARD=Other,DEV=0") == "hw:CARD=Other,DEV=0"
    assert real.find_mic(cards)["id"] == "U18dB"
    # without a HAT: a USB DAC wins over HDMI, the UMIK is never an output
    no_hat = [c for c in cards if c["id"] != "IQaudIODAC"]
    assert real.find_dac(no_hat) == "hw:CARD=vc4hdmi0,DEV=0"
    usb_dac = no_hat + [{"index": 4, "id": "Dragonfly", "driver": "USB-Audio", "name": "AudioQuest DragonFly"}]
    assert real.find_dac(usb_dac) == "hw:CARD=Dragonfly,DEV=0"


def test_rate_from_stop_reason():
    assert real._rate_from_reason({"CaptureFormatChange": 96000}) == 96000
    assert real._rate_from_reason("CaptureFormatChange(44100)") == 44100
    assert real._rate_from_reason("None") is None


def test_wav_roundtrip(tmp_path):
    x = np.sin(np.linspace(0, 20, 4800)) * 0.5
    real.write_wav(tmp_path / "a.wav", x)
    assert np.allclose(real.read_wav(tmp_path / "a.wav"), x, atol=1e-6)
    st = real.stereo(x, "R").reshape(-1, 2)
    assert not st[:, 0].any() and np.allclose(st[:, 1], x)


class FakeCamilla:
    """Speaks the CamillaDSP 3 websocket protocol."""

    def __init__(self):
        self.received = []
        self.state = "Running"
        self.stop_reason = "None"

    async def handler(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                break
            cmd = json.loads(msg.data)
            self.received.append(cmd)
            name = cmd if isinstance(cmd, str) else next(iter(cmd))
            value = {"GetState": self.state, "GetProcessingLoad": 3.5, "GetStopReason": self.stop_reason}.get(name)
            reply = {"result": "Ok"} if value is None else {"result": "Ok", "value": value}
            await ws.send_str(json.dumps({name: reply}))
        return ws


async def test_camilla_client_protocol(aiohttp_server):
    fake = FakeCamilla()
    app = web.Application()
    app.router.add_get("/", fake.handler)
    server = await aiohttp_server(app)
    rates = []
    client = real.CamillaClient(f"ws://127.0.0.1:{server.port}/", on_rate_change=rates.append)
    await client.set_config({"devices": {"samplerate": 44100}, "pipeline": []})   # before connecting
    await client.set_volume(-20)
    client.start()
    for _ in range(50):
        await asyncio.sleep(0.05)
        if client.state["load"] is not None:
            break
    names = [c if isinstance(c, str) else next(iter(c)) for c in fake.received]
    assert names[:4] == ["SetUpdateInterval", "SetConfigJson", "SetVolume", "SetMute"]   # config re-sent on connect
    assert json.loads(fake.received[1]["SetConfigJson"])["devices"]["samplerate"] == 44100
    assert fake.received[2] == {"SetVolume": -20.0}
    assert client.state["load"] == 3.5
    await client.set_volume(None)                                         # mute
    assert fake.received[-1] == {"SetMute": True}
    fake.state, fake.stop_reason = "Inactive", {"CaptureFormatChange": 96000}
    for _ in range(40):
        await asyncio.sleep(0.05)
        if rates:
            break
    assert rates and rates[0] == 96000
    await client.close()


async def test_player_hook_endpoint(client, device):
    r = await client.post("/api/v1/internal/source", json={"source": "airplay", "event": "start", "rate": 44100})
    assert r.status == 200
    s = await (await client.get("/api/v1/state")).json()
    assert s["player"]["source"] == "airplay" and s["player"]["signal"]["rate_in"] == 44100
    r = await client.post("/api/v1/internal/source", json={"source": "nope", "event": "start"})
    assert r.status == 400


IW_SCAN = """\
BSS 3c:a6:2f:11:22:33(on wlan0)
	freq: 2437
	signal: -48.00 dBm
	SSID: Zuhause
	RSN:	 * Version: 1
BSS 3c:a6:2f:11:22:34(on wlan0)
	freq: 5180
	signal: -61.00 dBm
	SSID: Zuhause
	RSN:	 * Version: 1
BSS 00:11:22:33:44:55(on wlan0)
	signal: -70.00 dBm
	capability: ESS ShortSlotTime (0x0401)
	SSID: Gast
BSS 00:11:22:33:44:66(on wlan0)
	signal: -80.00 dBm
	SSID: \\x00\\x00\\x00
	RSN:	 * Version: 1
"""


def test_parse_iw_scan():
    nets = real.parse_iw_scan(IW_SCAN)
    assert nets == [{"ssid": "Zuhause", "signal": -48, "secure": True},
                    {"ssid": "Gast", "signal": -70, "secure": False}]


def test_parse_ip_addr_iproute2_and_busybox():
    iproute = ("1: lo    inet 127.0.0.1/8 scope host lo\\       valid_lft forever\n"
               "2: eth0    inet 192.168.1.57/24 brd 192.168.1.255 scope global eth0\n"
               "3: wlan0    inet 192.168.4.1/24 scope global wlan0\n")
    assert real.parse_ip_addr(iproute) == {"eth0": "192.168.1.57", "wlan0": "192.168.4.1"}
    busybox = ("2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc mq qlen 1000\n"
               "    inet 192.168.1.57/24 brd 192.168.1.255 scope global eth0\n"
               "3: wlan0: <NO-CARRIER,BROADCAST,MULTICAST,UP> mtu 1500\n")
    assert real.parse_ip_addr(busybox) == {"eth0": "192.168.1.57"}


def test_iwd_profile(tmp_path):
    assert real.iwd_profile_name("Zuhause") == "Zuhause.psk"
    assert real.iwd_profile_name("FRITZ!Box 7590 XY") == "=" + "FRITZ!Box 7590 XY".encode().hex() + ".psk"
    assert real.iwd_profile_name("Gast", secure=False) == "Gast.open"
    p = real.write_iwd_profile(tmp_path, "Mein WLAN", "geheim1234")
    assert p.read_text() == "[Security]\nPassphrase=geheim1234\n"
    assert oct(p.stat().st_mode & 0o777) == "0o600"


def test_parse_bt_devices():
    text = "Device A4:C3:F0:11:22:33 iPhone von Anna\nDevice F0:99:11:22:33:44 Galaxy S24\nirrelevant\n"
    assert real.parse_bt_devices(text) == [{"address": "A4:C3:F0:11:22:33", "name": "iPhone von Anna"},
                                           {"address": "F0:99:11:22:33:44", "name": "Galaxy S24"}]


def test_loopback_rate_follows_player():
    from aroiod.real import LoopbackWatch, loopback_rate
    assert loopback_rate("closed\n") is None
    assert loopback_rate("access: MMAP_INTERLEAVED\nformat: S32_LE\nrate: 44100 (44100/1)\n") == 44100

    class D:
        calls = []
        def loopback_opened(self, r, f): self.calls.append((r, f))
    d = D()
    w = LoopbackWatch(d)
    a, b = (44100, "S16_LE"), (96000, "S32_LE")
    for r in (None, a, a, None, a, b):
        w.check(r)
    assert d.calls == [a, a, b]       # again after closing: CamillaDSP had stopped


def test_capture_released_on_device():
    from aroiod import dsp
    from aroiod.config import builtin_bypass
    cfg = dsp.camilla_config(builtin_bypass(), 44100, release_capture=True)
    assert cfg["devices"]["capture"]["stop_on_inactive"] is True
    assert "stop_on_inactive" not in dsp.camilla_config(builtin_bypass(), 44100)["devices"]["capture"]


def test_parse_bt_devices_with_prompt_and_colours():
    text = "\x1b[0;94m[bluetooth]\x1b[0m# Device B4:AE:C1:44:02:EA Melfs iPhone\r\n[bluetooth]# \n"
    assert real.parse_bt_devices(text) == [{"address": "B4:AE:C1:44:02:EA", "name": "Melfs iPhone"}]


async def test_bluetooth_list_follows_connections(monkeypatch):
    from aroiod import bt_watch as bw

    class Dev:
        source = None
        published = 0

        def publish_bluetooth(self):
            self.published += 1

    out = {"list-pcms": ""}

    async def fake_out(*cmd, timeout=4):
        return out.get(cmd[1], "")
    monkeypatch.setattr(bw, "_out", fake_out)
    d = Dev()
    w = bw.BluetoothWatch(d)
    await w.poll()
    assert d.published == 1                       # first look
    await w.poll()
    assert d.published == 1                       # nothing changed
    out["list-pcms"] = "/org/bluealsa/hci0/dev_B4_AE_C1_44_02_EA/a2dpsnk/source\n"
    await w.poll()
    assert d.published == 2 and w.connected == {"B4:AE:C1:44:02:EA"}


async def test_spotify_status_leaves_installing(monkeypatch, tmp_path):
    """The app got "installing" forever: the job published while it was still running."""
    import asyncio
    from aroiod import soloist
    world = real.RealWorld()
    seen = []

    class Secrets:
        def has(self, key):
            return True

    class Dev:
        config = type("C", (), {"get": staticmethod(lambda k: "Aroio")})()

        def publish_services(self):
            seen.append(world.spotify_status(Secrets())["status"])

    world.device = Dev()
    binary = tmp_path / "soloist"
    binary.write_text("x")
    monkeypatch.setattr(soloist, "BIN", binary)
    monkeypatch.setattr(soloist, "update", lambda force: "geladen")
    monkeypatch.setattr(soloist, "info", lambda: {"installed": True, "version": "1.3"})

    async def noop(*a, **k):
        return True, ""
    monkeypatch.setattr(real, "_output_ok", noop)
    world._soloist_install()
    await asyncio.sleep(0.2)
    assert seen[0] == "installing" and seen[-1] == "ready"


async def test_fetch_reads_whole_body_in_chunks(aiohttp_server):
    """Through a proxy the body arrives in small pieces: fetch() must not stop at the first
    (it did: 'Unterminated string starting at: line 1 column 65716')."""
    import json as _json
    body = _json.dumps({"tree": [{"path": "x" * 50, "type": "blob"}] * 4000}).encode()

    async def handler(request):
        resp = web.StreamResponse()
        await resp.prepare(request)
        for i in range(0, len(body), 1000):
            await resp.write(body[i:i + 1000])
            await asyncio.sleep(0)
        await resp.write_eof()
        return resp
    app = web.Application()
    app.router.add_get("/tree", handler)
    server = await aiohttp_server(app)
    w = real.RealWorld.__new__(real.RealWorld)
    data = await w.fetch(str(server.make_url("/tree")))
    assert data == body and len(body) > 200_000
