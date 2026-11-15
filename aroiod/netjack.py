"""NetJack 2 on the device: python -m aroiod.netjack (unit aroio-netjack.service).

The Aroio is the NetJack master like in AroioOS 5.1: computers running
`jackd -d net` find it by multicast and send their audio. Unlike 5.1 JACK must not
hold the audio path all the time (exactly one source plays, the loopback takes one
rate), so:

- jackd runs on the dummy driver (no sound card) with the `netmanager` internal client;
- only while a computer is connected the `audioadapter` internal client opens
  plughw:Loopback,0,0 and the computer's ports are connected to it;
- aroiod pauses NetJack (another source starts) with SIGUSR1: the adapter closes and
  stays closed until that computer disconnects, so it cannot take the speaker back.

jack_load and jack_lsp are not part of jack2 any more, so libjack is used through ctypes.
"""

import ctypes
import json
import logging
import os
import signal
import subprocess
import sys
import time
import urllib.request

log = logging.getLogger("aroiod.netjack")

JackNoStartServer = 0x01
JackLoadName = 0x08
JackLoadInit = 0x10
JackPortIsInput = 0x1
JackPortIsOutput = 0x2

ADAPTER = "aroio-out"
EVENT_URL = "http://127.0.0.1/api/v1/internal/source"


class Jack:
    """The few libjack calls needed here."""

    def __init__(self, name="aroio-netjack", lib="libjack.so.0"):
        self.lib = lib = ctypes.CDLL(lib)
        lib.jack_client_open.restype = ctypes.c_void_p
        lib.jack_get_ports.restype = ctypes.POINTER(ctypes.c_char_p)
        lib.jack_get_ports.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_ulong]
        lib.jack_free.argtypes = [ctypes.c_void_p]
        lib.jack_connect.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
        lib.jack_internal_client_load.restype = ctypes.c_uint64
        lib.jack_internal_client_unload.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
        lib.jack_client_close.argtypes = [ctypes.c_void_p]
        status = ctypes.c_int(0)
        self.client = lib.jack_client_open(name.encode(), JackNoStartServer, ctypes.byref(status))
        if not self.client:
            raise OSError(f"JACK-Server nicht erreichbar (Status {status.value:#x})")

    def ports(self, pattern, flags=0):
        arr = self.lib.jack_get_ports(self.client, pattern.encode(), None, flags)
        if not arr:
            return []
        out, i = [], 0
        while arr[i]:
            out.append(arr[i].decode())
            i += 1
        self.lib.jack_free(arr)
        return out

    def connect(self, src, dst):
        return self.lib.jack_connect(self.client, src.encode(), dst.encode()) in (0, 17)   # 17 = EEXIST

    def load(self, name, so, init=""):
        status = ctypes.c_int(0)
        handle = self.lib.jack_internal_client_load(
            ctypes.c_void_p(self.client), name.encode(), JackLoadName | JackLoadInit, ctypes.byref(status),
            ctypes.c_char_p(so.encode()), ctypes.c_char_p(init.encode()))
        if not handle:
            raise OSError(f"{so} ließ sich nicht laden (Status {status.value:#x})")
        return handle

    def unload(self, handle):
        self.lib.jack_internal_client_unload(self.client, handle)

    def close(self):
        if self.client:
            self.lib.jack_client_close(self.client)
            self.client = None


def slaves(ports):
    """'studio:from_slave_1' … -> {'studio': ['studio:from_slave_1', …]} (ports in order)."""
    out = {}
    for p in ports:
        client, _, short = p.partition(":")
        if short.startswith("from_slave_"):
            out.setdefault(client, []).append(p)
    for v in out.values():
        v.sort(key=lambda p: int(p.rsplit("_", 1)[1]) if p.rsplit("_", 1)[1].isdigit() else 0)
    return out


class Controller:
    """Opens the way to the loopback while a computer is connected (one tick per second)."""

    def __init__(self, jack, post, adapter_init):
        self.jack, self.post, self.adapter_init = jack, post, adapter_init
        self.adapter = None
        self.playing = None          # name of the connected computer
        self.suppressed = None       # computer that was paused by aroiod

    def tick(self):
        connected = slaves(self.jack.ports(":from_slave_", JackPortIsOutput))
        if self.suppressed and self.suppressed not in connected:
            self.suppressed = None
        if self.playing and self.playing not in connected:
            self._close()
            self.post({"source": "netjack", "event": "stop"})
        if self.playing or not connected:
            return
        name = next((n for n in connected if n != self.suppressed), None)
        if not name:
            return
        self.adapter = self.jack.load(ADAPTER, "audioadapter", self.adapter_init)
        for i, port in enumerate(connected[name][:2], start=1):
            self.jack.connect(port, f"{ADAPTER}:playback_{i}")
        if len(connected[name]) == 1:                       # mono computer: both speakers
            self.jack.connect(connected[name][0], f"{ADAPTER}:playback_2")
        self.playing = name
        self.post({"source": "netjack", "event": "start",
                   "meta": {"title": "NetJack", "artist": name, "album": "", "duration": 0, "live": True}})

    def pause(self):
        """Another source plays now: let go of the loopback until this computer disconnects."""
        if self.playing:
            self.suppressed = self.playing
            self._close()

    def _close(self):
        if self.adapter:
            try:
                self.jack.unload(self.adapter)
            except OSError as exc:
                log.warning("unload: %s", exc)
        self.adapter, self.playing = None, None

    def shutdown(self):
        self._close()


def post_event(data):
    req = urllib.request.Request(EVENT_URL, json.dumps(data).encode(), {"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=3).read()
    except OSError as exc:
        log.warning("aroiod: %s", exc)


def main():
    logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s %(message)s")
    rate = os.environ.get("NETJACK_RATE", "48000")
    period = os.environ.get("NETJACK_PERIOD", "1024")
    jackd = subprocess.Popen(["jackd", "--no-realtime" if os.environ.get("NETJACK_NORT") else "-R",
                              "-d", "dummy", "-r", rate, "-p", period, "-C", "0", "-P", "0"])
    jack = None
    for _ in range(50):
        try:
            jack = Jack()
            break
        except OSError:
            if jackd.poll() is not None:
                sys.exit("jackd beendet")
            time.sleep(0.2)
    if jack is None:
        jackd.terminate()
        sys.exit("JACK-Server startet nicht")
    netmanager = jack.load("netmanager", "netmanager", os.environ.get("NETJACK_MANAGER_ARGS", ""))
    adapter_init = os.environ.get(
        "NETJACK_ADAPTER_ARGS",
        # the adapter always opens a capture device too: an unused loopback subdevice
        f"-P plughw:Loopback,0,0 -C hw:Loopback,1,7 -i 0 -o 2 -r {rate} -p {period} -n 3 -q 3")
    ctl = Controller(jack, post_event, adapter_init)
    flags = {"pause": False, "stop": False}
    signal.signal(signal.SIGUSR1, lambda *_: flags.__setitem__("pause", True))
    signal.signal(signal.SIGTERM, lambda *_: flags.__setitem__("stop", True))
    log.info("NetJack-Master bereit (%s Hz)", rate)
    try:
        while not flags["stop"] and jackd.poll() is None:
            if flags["pause"]:
                flags["pause"] = False
                ctl.pause()
            try:
                ctl.tick()
            except OSError as exc:
                log.warning("%s", exc)
            time.sleep(1)
    finally:
        ctl.shutdown()
        jack.unload(netmanager)
        jack.close()
        jackd.terminate()
        try:
            jackd.wait(5)
        except subprocess.TimeoutExpired:
            jackd.kill()
    sys.exit(0 if flags["stop"] else 1)


if __name__ == "__main__":
    main()
