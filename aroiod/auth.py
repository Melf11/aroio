"""Optional password for the app (old Aroio: USERPASSWD).

Off by default (home network device). When on, every API call and the live
sockets need a session cookie; the app shell itself loads and shows a login.
The password is stored as an scrypt hash in secrets.json, sessions survive a
restart. Players on the device (aroio-event) and the captive portal are exempt.
"""

import hashlib
import hmac
import os
import secrets as pysecrets
import time

COOKIE = "aroio_session"
MAX_SESSIONS = 20
OPEN_PATHS = ("/api/v1/auth/", "/api/v1/internal/")


def _hash(password, salt):
    return hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32).hex()


class Auth:
    def __init__(self, device):
        self.device = device
        s = device.secrets
        legacy = s.get("app.password")              # plain text from the migration
        if legacy:
            self._store(legacy)
            s.set("app.password", None)

    @property
    def enabled(self):
        return bool(self.device.config.get("security.app_password")) and self.device.secrets.has("app.password_hash")

    def _store(self, password):
        salt = os.urandom(16)
        self.device.secrets.set("app.password_hash", f"{salt.hex()}:{_hash(password, salt)}")

    def check(self, password):
        stored = self.device.secrets.get("app.password_hash") or ""
        if ":" not in stored:
            return False
        salt, digest = stored.split(":", 1)
        return hmac.compare_digest(_hash(password or "", bytes.fromhex(salt)), digest)

    def set_password(self, password):
        """None or empty: protection off. Else at least 4 characters."""
        if not password:
            self.device.secrets.set("app.password_hash", None)
            self.device.secrets.set("app.sessions", None)
            self.device.patch_config({"security": {"app_password": False}})
            return None
        if len(password) < 4:
            raise ValueError("Das Passwort braucht mindestens 4 Zeichen.")
        self._store(password)
        self.device.patch_config({"security": {"app_password": True}})
        return self.new_session()

    def new_session(self):
        token = pysecrets.token_urlsafe(32)
        sessions = [x for x in (self.device.secrets.get("app.sessions") or []) if isinstance(x, dict)]
        sessions = (sessions + [{"t": hashlib.sha256(token.encode()).hexdigest(), "at": int(time.time())}])[-MAX_SESSIONS:]
        self.device.secrets.set("app.sessions", sessions)
        return token

    def valid(self, token):
        if not token:
            return False
        h = hashlib.sha256(token.encode()).hexdigest()
        return any(hmac.compare_digest(h, x.get("t", "")) for x in self.device.secrets.get("app.sessions") or [])

    def end_session(self, token):
        if token:
            h = hashlib.sha256(token.encode()).hexdigest()
            self.device.secrets.set("app.sessions", [x for x in self.device.secrets.get("app.sessions") or [] if x.get("t") != h] or None)

    def allowed(self, request):
        if not self.enabled or not request.path.startswith("/api/"):
            return True
        if request.path.startswith(OPEN_PATHS):
            return True
        return self.valid(request.cookies.get(COOKIE))
