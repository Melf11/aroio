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
    assert names[:3] == ["SetConfigJson", "SetVolume", "SetMute"]        # config re-sent on connect
    assert json.loads(fake.received[0]["SetConfigJson"])["devices"]["samplerate"] == 44100
    assert fake.received[1] == {"SetVolume": -20.0}
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
