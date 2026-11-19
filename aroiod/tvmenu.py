"""Menu on the HDMI info screen, operated with the TV remote over CEC.

Keys (rc-cec names, see aroiod/inputs.py CEC_KEYS):
    closed:  OK / Menu opens the menu, Up / Down volume, Left / Right previous / next title,
             Play / Pause / Stop / Forward / Backward as labelled
    open:    Up / Down choose, OK does it, Left / Right change a value (volume),
             Back / Exit one level up (closes from the top), closes itself after 20 s

The menu lives in aroiod (Device.tvmenu); the screen only draws `state()`, which
/api/v1/internal/status hands out. `rev` counts changes, so the screen can wait for one.
"""

import asyncio
import time

CLOSE_AFTER = 20.0          # s without a key
OVERLAY_FOR = 3.0           # s the volume bubble stays after Up/Down with the menu closed


class TVMenu:
    def __init__(self, device):
        self.d = device
        self.stack = []             # [(menu id, index)]; empty = closed
        self.last_key = 0.0
        self.overlay_until = 0.0
        self.rev = 0
        self._changed = asyncio.Event() if _loop_running() else None

    # ── what the screen shows ──
    def state(self, now=None):
        now = now or time.monotonic()
        if self.stack and now - self.last_key > CLOSE_AFTER:
            self.stack = []
        out = {"rev": self.rev, "open": bool(self.stack), "volume_overlay": now < self.overlay_until}
        if self.stack:
            menu_id, index = self.stack[-1]
            title, items = self._menu(menu_id)
            out.update(title=title, index=min(index, max(0, len(items) - 1)),
                       items=[{k: v for k, v in i.items() if not callable(v) and k != "do"} for i in items],
                       depth=len(self.stack))
        return out

    def _menu(self, menu_id):
        d = self.d
        if menu_id == "main":
            items = []
            if d.state == "playing":
                items.append({"label": "Pause", "do": d.pause})
            elif d.source:
                items.append({"label": "Weiter abspielen", "do": d.play})
            if d.source:
                items.append({"label": "Nächster Titel", "do": d.next})
            if not d.fixed_level:
                items.append({"label": "Lautstärke", "value": f"{d.volume} %", "adjust": True,
                              "do": None, "step": self._volume})
            items.append({"label": "Klang", "value": self._preset_name(), "open": "sound"})
            if d.library.favorites and d.config.get("sources.lms.enabled", True):
                items.append({"label": "Favoriten", "open": "favorites"})
            items.append({"label": "Schließen", "do": self.close})
            return "Aroio", items
        if menu_id == "sound":
            dsp = d.config.data["dsp"]
            active = dsp["active_preset"] if dsp["enabled"] else None
            items = [{"label": p["name"], "active": p["id"] == active,
                      "do": (lambda pid=p["id"]: d.patch_config({"dsp": {"active_preset": pid, "enabled": True}}))}
                     for p in dsp["presets"] if p["id"] != "preview"]
            items.append({"label": "Mono", "value": "an" if dsp.get("mono") else "aus",
                          "do": lambda: d.patch_config({"dsp": {"mono": not dsp.get("mono")}})})
            return "Klang", items
        if menu_id == "favorites":
            items = []
            for fid in d.library.favorites[:30]:
                try:
                    item = d.library.item(fid)
                except (KeyError, ValueError):
                    continue
                items.append({"label": item.get("title") or fid, "value": item.get("subtitle") or "",
                              "do": (lambda i=fid: d.play_items(i)), "close": True})
            return "Favoriten", items
        return "", []

    def _preset_name(self):
        dsp = self.d.config.data["dsp"]
        if not dsp["enabled"]:
            return "aus"
        return next((p["name"] for p in dsp["presets"] if p["id"] == dsp["active_preset"]), "")

    def _volume(self, direction):
        self.d.set_volume(delta=direction * self.d.config.get("hardware.encoder_step"))

    # ── keys ──
    def key(self, name):
        """A key from the TV remote; True when the menu used it."""
        now = time.monotonic()
        self.last_key = now
        if not self.stack:
            return self._closed_key(name, now)
        menu_id, index = self.stack[-1]
        _, items = self._menu(menu_id)
        if not items:
            self.back()
            return True
        index = min(index, len(items) - 1)
        item = items[index]
        if name == "KEY_UP":
            self.stack[-1] = (menu_id, (index - 1) % len(items))
        elif name == "KEY_DOWN":
            self.stack[-1] = (menu_id, (index + 1) % len(items))
        elif name in ("KEY_LEFT", "KEY_RIGHT"):
            if item.get("step"):
                item["step"](1 if name == "KEY_RIGHT" else -1)
            elif name == "KEY_LEFT":
                self.back()
            elif item.get("open"):
                self.stack.append((item["open"], 0))
        elif name in ("KEY_OK", "KEY_SELECT", "KEY_ENTER"):
            if item.get("open"):
                self.stack.append((item["open"], 0))
            elif item.get("do"):
                item["do"]()
                if item.get("close"):
                    self.stack = []
        elif name in ("KEY_BACK", "KEY_EXIT", "KEY_ESC"):
            self.back()
        elif name in ("KEY_MENU", "KEY_ROOT_MENU"):
            self.close()
        else:
            return False
        self.changed()
        return True

    def _closed_key(self, name, now):
        d = self.d
        if name in ("KEY_OK", "KEY_SELECT", "KEY_ENTER", "KEY_MENU", "KEY_ROOT_MENU"):
            self.stack = [("main", 0)]
        elif name in ("KEY_UP", "KEY_DOWN") and not d.fixed_level:
            self._volume(1 if name == "KEY_UP" else -1)
            self.overlay_until = now + OVERLAY_FOR
        elif name == "KEY_LEFT":
            d.previous()
        elif name == "KEY_RIGHT":
            d.next()
        else:
            return False
        self.changed()
        return True

    def back(self):
        if self.stack:
            self.stack.pop()
        self.changed()

    def close(self):
        self.stack = []
        self.changed()

    def changed(self):
        self.rev += 1
        if self._changed is None and _loop_running():
            self._changed = asyncio.Event()
        if self._changed:
            self._changed.set()

    async def wait(self, rev, timeout):
        """Until rev changes (a key) or timeout: the screen reacts at once."""
        if self.rev != rev or not _loop_running():
            return
        if self._changed is None:
            self._changed = asyncio.Event()
        self._changed.clear()
        try:
            await asyncio.wait_for(self._changed.wait(), timeout)
        except asyncio.TimeoutError:
            pass


def _loop_running():
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False
