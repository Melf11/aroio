"""Live state, split into topics, pushed to every open app over WebSocket.

A topic is replaced as a whole on change (they are small). Nothing is polled:
with no app open, no work is done.
"""

import asyncio
import copy
import json
import logging

log = logging.getLogger("aroiod.hub")


class Hub:
    def __init__(self):
        self.topics = {}
        self._subs = set()

    def snapshot(self):
        return copy.deepcopy(self.topics)

    def publish(self, topic, data):
        if self.topics.get(topic) == data:
            return
        self.topics[topic] = copy.deepcopy(data)
        self._send({"type": "topic", "topic": topic, "data": data})

    def notice(self, text, level="info", key=None):
        """Transient message for the app (announced by screen readers)."""
        self._send({"type": "notice", "level": level, "text": text, "key": key})

    def _send(self, msg):
        raw = json.dumps(msg, ensure_ascii=False)
        for q in list(self._subs):
            if q.qsize() > 200:        # a stuck client must not grow memory
                self._subs.discard(q)
                continue
            q.put_nowait(raw)

    def subscribe(self):
        q = asyncio.Queue()
        self._subs.add(q)
        return q

    def unsubscribe(self, q):
        self._subs.discard(q)

    @property
    def clients(self):
        return len(self._subs)
