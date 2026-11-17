"""HTTP proxy for networks without direct internet access (company networks).

The app enters one address, http://user:password@proxy.example:3128. The password goes
to secrets.json, config.json keeps the address without it (network.proxy.url/user).

On the device the full address becomes /data/aroio/proxy.env (0600), read by the units
that fetch from the internet (Spotify, its updater, MPD/upmpdcli), and aroiod sets the
same variables for itself: its own internet requests (updates, headphone filters,
Spotify download) use them, requests in the home network never do (NO_PROXY).

Many company proxies open HTTPS and sign it with the company's own root certificate (TLS
inspection). That certificate can be added (proxy-ca.pem in the data directory): the
programs then trust ca-bundle.pem, the system's certificates plus it (SSL_CERT_FILE ...).
"""

import os
import re
import ssl
from urllib.parse import quote, unquote, urlsplit

from .config import Invalid

FIELD = "network.proxy"
# local names and private networks never go through the proxy (curl understands CIDR,
# Python's urllib only names; aroiod's local requests do not read the variables at all)
NO_PROXY = ("localhost,127.0.0.1,::1,.local,"
            "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,169.254.0.0/16,fc00::/7,fe80::/10")


def parse(text):
    """'http://user:pw@host:port' -> (url without credentials, user, password); '' -> ('', '', '')."""
    text = (text or "").strip()
    if not text:
        return "", "", ""
    if "://" not in text:
        text = "http://" + text
    try:
        u = urlsplit(text)
        port = u.port
    except ValueError:
        raise Invalid(FIELD, "Die Proxy-Adresse ist ungültig. Beispiel: http://proxy.firma.de:8080") from None
    if u.scheme != "http":
        raise Invalid(FIELD, "Nur HTTP-Proxys werden unterstützt (Adresse beginnt mit http://).")
    if not u.hostname:
        raise Invalid(FIELD, "Bitte den Namen oder die IP-Adresse des Proxys angeben.")
    if not port:
        raise Invalid(FIELD, "Bitte den Port des Proxys angeben, z. B. :8080.")
    if u.path not in ("", "/") or u.query or u.fragment:
        raise Invalid(FIELD, "Die Proxy-Adresse hat keinen Pfad, nur http://name:port.")
    host = f"[{u.hostname}]" if ":" in u.hostname else u.hostname
    user, password = unquote(u.username or ""), unquote(u.password or "")
    if len(user) > 100 or len(password) > 200 or len(host) > 200:
        raise Invalid(FIELD, "Die Proxy-Adresse ist zu lang.")
    return f"http://{host}:{port}", user, password


def compose(url, user="", password=""):
    """Full address with credentials (percent-encoded), '' when no proxy is set."""
    if not url:
        return ""
    if not user:
        return url
    cred = quote(user, safe="") + (":" + quote(password, safe="") if password else "")
    return url.replace("http://", f"http://{cred}@", 1)


def display(url, user="", password_set=False):
    """For the app: the address with the password hidden."""
    if not url:
        return ""
    if not user:
        return url
    return url.replace("http://", f"http://{quote(user, safe='')}{':••••' if password_set else ''}@", 1)


CA_FILE = "proxy-ca.pem"
BUNDLE_FILE = "ca-bundle.pem"
PROXY_KEYS = ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "no_proxy", "NO_PROXY")
# OpenSSL (Python, curl), curl's own name, Python requests
CA_KEYS = ("SSL_CERT_FILE", "CURL_CA_BUNDLE", "REQUESTS_CA_BUNDLE")
SYSTEM_BUNDLES = ("/etc/ssl/certs/ca-certificates.crt", "/etc/ssl/cert.pem")


def environment(full, cafile=None):
    """Variables for programs ({} = none). Both spellings: curl reads lower case."""
    env = {}
    if full:
        env.update({"http_proxy": full, "https_proxy": full, "HTTP_PROXY": full, "HTTPS_PROXY": full,
                    "no_proxy": NO_PROXY, "NO_PROXY": NO_PROXY})
    if cafile:
        env.update({k: str(cafile) for k in CA_KEYS})
    return env


def env_file(full, cafile=None):
    """Contents of proxy.env (systemd EnvironmentFile). Percent-encoding keeps it free of
    quotes, spaces and $."""
    return "".join(f"{k}={v}\n" for k, v in environment(full, cafile).items())


def parse_ca(data):
    """Uploaded certificate (PEM, or DER as Keychain/Windows export it) -> (PEM text, names
    of the root certificates in it). Only CA certificates are accepted."""
    if isinstance(data, str):
        data = data.encode()
    if b"-----BEGIN CERTIFICATE-----" in data:
        pem = "\n".join(m.decode() for m in re.findall(
            rb"-----BEGIN CERTIFICATE-----[A-Za-z0-9+/=\s]+?-----END CERTIFICATE-----", data))
    else:
        try:
            pem = ssl.DER_cert_to_PEM_cert(data)
        except (ValueError, TypeError):
            pem = ""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    try:
        if not pem:
            raise ssl.SSLError
        ctx.load_verify_locations(cadata=pem)
    except ssl.SSLError:
        raise Invalid(FIELD, "Das ist kein lesbares Zertifikat (erwartet: .crt, .cer oder .pem).") from None
    names = []
    for cert in ctx.get_ca_certs():
        subject = dict(x[0] for x in cert.get("subject", ()))
        names.append(subject.get("commonName") or subject.get("organizationName") or "Zertifikat")
    if not names:
        raise Invalid(FIELD, "Das Zertifikat ist kein Stammzertifikat (CA). Bitte das Stammzertifikat "
                             "der Firma nehmen, nicht das einer Webseite.")
    return pem.strip() + "\n", names


def ca_names(pem):
    try:
        return parse_ca(pem)[1]
    except Invalid:
        return []


def bundle(ca_pem):
    """The system's root certificates plus the company's."""
    for path in [ssl.get_default_verify_paths().openssl_cafile, *SYSTEM_BUNDLES]:
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                return fh.read().rstrip("\n") + "\n" + ca_pem
        except OSError:
            continue
    return ca_pem


def ssl_context():
    """A fresh default context: it reads SSL_CERT_FILE now (aiohttp's own is made at import).
    With a company certificate the strict RFC 5280 form checks of Python 3.13+ are off: the
    certificates a TLS-inspecting proxy makes up often lack e.g. the Authority Key Identifier
    (curl and browsers accept them); trust and host name are still checked."""
    ctx = ssl.create_default_context()
    if os.environ.get("SSL_CERT_FILE"):
        ctx.verify_flags &= ~getattr(ssl, "VERIFY_X509_STRICT", 0)
    return ctx


_SECRET_RES = (re.compile(r"(password=')[^']*(')"), re.compile(r"(://[^:/@\s]+:)[^@\s]+(@)"))


def redact(text):
    """Logs and the diagnosis package must not show the proxy password."""
    text = str(text)
    for rx in _SECRET_RES:
        text = rx.sub(r"\1•••\2", text)
    full = os.environ.get("https_proxy", "")
    try:
        password = unquote(urlsplit(full).password or "") if full else ""
    except ValueError:
        password = ""
    if len(password) >= 3:
        text = text.replace(password, "•••").replace(quote(password, safe=""), "•••")
    return text
