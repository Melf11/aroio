"""Live level meter: peak and RMS per channel of the signal that goes to the DAC.

One polling task for all open meters (15 per second), started with the first
listener and stopped with the last one: with no app showing a meter, nothing
is polled. The world delivers the values (CamillaDSP GetSignalLevelsSinceLast
on the device, a plausible music-like signal in the simulator).
"""

import asyncio
import json
import logging

log = logging.getLogger("aroiod.levels")

FLOOR = -100.0


class Levels:
    def __init__(self, device, rate=15.0):
        self.device = device
        self.interval = 1.0 / rate
        self._subs = set()
        self._task = None

    def subscribe(self):
        q = asyncio.Queue(maxsize=3)
        self._subs.add(q)
        if self._task is None or self._task.done():
            self._task = asyncio.ensure_future(self._run())
        return q

    def unsubscribe(self, q):
        self._subs.discard(q)

    async def _run(self):
        while self._subs:
            try:
                values = await self.device.world.levels()
            except Exception as exc:  # noqa: BLE001
                log.debug("levels: %s", exc)
                values = None
            if values:
                msg = json.dumps(values)
                for q in list(self._subs):
                    if q.full():          # a slow client gets the newest values, not a backlog
                        q.get_nowait()
                    q.put_nowait(msg)
            await asyncio.sleep(self.interval)


def clean(peak, rms):
    """dB lists from CamillaDSP -> rounded values, silence as FLOOR."""
    def fix(v):
        try:
            v = float(v)
        except (TypeError, ValueError):
            return FLOOR
        return round(max(FLOOR, min(6.0, v)), 1) if v == v else FLOOR   # NaN -> floor
    return {"peak": [fix(v) for v in peak[:2]], "rms": [fix(v) for v in rms[:2]]}
