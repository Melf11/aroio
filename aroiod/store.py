"""Persistence: atomic JSON files and the secrets store.

Every file under /data has exactly one writer: aroiod. Files are written via
temp file + fsync + rename (+ fsync of the directory), so a power cut leaves
either the old or the new file, never a truncated one.
"""

import json
import logging
import os
from pathlib import Path

log = logging.getLogger("aroiod.store")


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default
    except (OSError, ValueError) as exc:
        log.error("Cannot read %s (%s), using defaults", path, exc)
        return default


def atomic_write_json(path, data, mode=0o644):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    try:
        dfd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError:
        pass


def atomic_write_bytes(path, data, mode=0o644):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


class Secrets:
    """Passwords and tokens, kept apart from config.json (mode 0600) and never
    sent to the app. The app only learns whether a secret is set."""

    def __init__(self, path):
        self.path = Path(path)
        self._data = load_json(self.path, {})

    def get(self, key, default=None):
        return self._data.get(key, default)

    def has(self, key):
        return bool(self._data.get(key))

    def set(self, key, value):
        if value in (None, ""):
            self._data.pop(key, None)
        else:
            self._data[key] = value
        atomic_write_json(self.path, self._data, mode=0o600)

    def delete_prefix(self, prefix):
        for key in [k for k in self._data if k.startswith(prefix)]:
            del self._data[key]
        atomic_write_json(self.path, self._data, mode=0o600)
