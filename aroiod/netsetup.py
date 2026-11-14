"""Network setup: setup hotspot with captive portal and guided WLAN connection.

    no cable and no WLAN after boot  ->  open hotspot "Aroio-Einrichtung-XXXX"
    phone joins  ->  captive portal opens /einrichtung (web.captive middleware)
    user picks WLAN + password  ->  hotspot off, connect
         success: hotspot stays off, the Aroio is in the home network
         failure: hotspot comes back, the page shows why

Same logic in the simulator and on the device; the world provides the
primitives: links(), wifi_scan(), hotspot_start(ssid), hotspot_stop(),
wifi_join(ssid, psk, timeout) -> (ok, error), id_suffix().
"""

import asyncio
import logging
import time

log = logging.getLogger("aroiod.netsetup")

HOTSPOT_ADDRESS = "192.168.4.1"
PORTAL_PATH = "/einrichtung"


class NetSetup:
    def __init__(self, device, grace=25.0, interval=3.0, switch_delay=1.5, join_timeout=25.0):
        self.device = device
        self.world = device.world
        self.grace, self.interval = grace, interval
        self.switch_delay, self.join_timeout = switch_delay, join_timeout
        self.active = False
        self.ssid = None
        self.networks = []
        self.attempt = {"state": "idle", "ssid": None, "error": None, "at": None}
        self.started = time.monotonic()
        self._task = None
        self._busy = asyncio.Lock()

    # ── state for the app (merged into the "network" topic) ──
    def status(self):
        return {"hotspot": {"active": self.active, "ssid": self.ssid, "address": HOTSPOT_ADDRESS if self.active else None,
                            "portal": f"http://{HOTSPOT_ADDRESS}{PORTAL_PATH}" if self.active else None},
                "setup": dict(self.attempt), "networks": self.networks if self.active else []}

    def start(self):
        self._task = asyncio.ensure_future(self._run())

    async def _run(self):
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("network setup")
            await asyncio.sleep(self.interval)

    async def tick(self):
        if self._busy.locked():
            return
        links = self.world.links()
        mode = self.device.config.get("network.hotspot")
        if self.active and (links["lan"] or mode == "off"):
            await self.stop()
        elif (not self.active and mode == "auto" and not links["lan"] and not links["wifi"]
              and links.get("wlan_present", True) and time.monotonic() - self.started > self.grace):
            await self.begin()

    async def begin(self):
        async with self._busy:
            try:
                self.networks = await self.world.wifi_scan()       # before: the radio is busy as hotspot
            except Exception as exc:  # noqa: BLE001
                log.warning("scan before hotspot failed: %s", exc)
                self.networks = []
            self.ssid = f"Aroio-Einrichtung-{self.world.id_suffix()}"
            await self.world.hotspot_start(self.ssid)
            self.active = True
            log.info("setup hotspot %s started", self.ssid)
            self.device.publish_network()

    async def stop(self):
        async with self._busy:
            await self.world.hotspot_stop()
            self.active = False
            log.info("setup hotspot stopped")
            self.device.publish_network()

    async def scan(self):
        """While the hotspot runs, the list from before it started (scanning would drop the phone)."""
        if self.active:
            return self.networks
        return await self.world.wifi_scan()

    async def connect(self, ssid, psk):
        """Returns {"switching": True} if the phone will lose the hotspot now."""
        if self.active:
            self.attempt = {"state": "connecting", "ssid": ssid, "error": None, "at": time.time()}
            self.device.publish_network()
            asyncio.ensure_future(self._switch(ssid, psk))
            return {"switching": True}
        ok, error = await self.world.wifi_join(ssid, psk, self.join_timeout)
        if not ok:
            raise ValueError(error)
        self._remember(ssid, psk)
        return {"switching": False}

    async def _switch(self, ssid, psk):
        await asyncio.sleep(self.switch_delay)     # let the page show the instructions first
        async with self._busy:
            await self.world.hotspot_stop()
            self.active = False
            ok, error = await self.world.wifi_join(ssid, psk, self.join_timeout)
            if ok:
                self._remember(ssid, psk)
                self.attempt = {"state": "connected", "ssid": ssid, "error": None, "at": time.time()}
                log.info("connected to %s", ssid)
            else:
                self.attempt = {"state": "failed", "ssid": ssid, "error": error, "at": time.time()}
                log.info("connecting to %s failed: %s; hotspot again", ssid, error)
        if not ok:
            await self.begin()
        self.device.publish_network()

    def _remember(self, ssid, psk):
        self.device.secrets.set("wifi.psk", psk)
        self.device.patch_config({"network": {"wifi": {"ssid": ssid, "enabled": True}}})

    # ── captive portal ──
    def is_foreign_host(self, host, path):
        """While the hotspot runs, every request that is not for the Aroio (captive
        portal probes of iOS, Android, Windows, Firefox ...) is sent to the setup page."""
        if not self.active:
            return False
        name = (host or "").split(":")[0].lower()
        own = {HOTSPOT_ADDRESS, "localhost", "127.0.0.1", "aroio.local",
               f"{self.device.config.get('network.hostname')}.local"}
        if name not in own:
            return True
        return path in ("/hotspot-detect.html", "/library/test/success.html", "/generate_204", "/gen_204",
                        "/connecttest.txt", "/ncsi.txt", "/redirect", "/canonical.html", "/success.txt")
