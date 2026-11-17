"""HTTP proxy for networks without direct internet access (company networks).

The app enters one address, http://user:password@proxy.example:3128. The password goes
to secrets.json, config.json keeps the address without it (network.proxy.url/user).

On the device the full address becomes /data/aroio/proxy.env (0600), read by the units
that fetch from the internet (Spotify, its updater, MPD/upmpdcli), and aroiod sets the
same variables for itself: its own internet requests (updates, headphone filters,
Spotify download) use them, requests in the home network never do (NO_PROXY).
"""

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


def environment(full):
    """Variables for programs ({} = no proxy). Both spellings: curl reads lower case."""
    if not full:
        return {}
    return {"http_proxy": full, "https_proxy": full, "HTTP_PROXY": full, "HTTPS_PROXY": full,
            "no_proxy": NO_PROXY, "NO_PROXY": NO_PROXY}


def env_file(full):
    """Contents of proxy.env (systemd EnvironmentFile). Percent-encoding keeps it free of
    quotes, spaces and $."""
    return "".join(f"{k}={v}\n" for k, v in environment(full).items())
