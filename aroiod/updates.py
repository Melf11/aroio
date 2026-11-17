"""Updates from GitHub releases: which release fits the device and its channel.

Stable = the newest release that is not a pre-release, beta = the newest of all.
A device running a pre-release stays on the beta track whatever its channel says:
otherwise a beta install is never offered the next beta (or anything until a release).
A release carries the RAUC bundle (`*.raucb`) as an asset; its body (Markdown)
gives the notes shown in the app (bullet lines).
"""

import re

REPO = "Melf11/aroio"
API = "https://api.github.com/repos/{repo}/releases?per_page=20"

_NUM = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$")


def parse_version(text):
    """'v1.2.3-beta.1' -> (1, 2, 3, (0, 'beta', 1)); release > pre-release of the same number.
    Development builds ('dev', '0.1.0-dev') are lower than every release."""
    m = _NUM.match((text or "").strip())
    if not m:
        return None
    major, minor, patch, pre = m.groups()
    if pre is None:
        tail = (1,)
    else:
        parts = tuple(int(p) if p.isdigit() else p for p in pre.split("."))
        tail = (0,) + tuple((0, p) if isinstance(p, int) else (1, p) for p in parts)
    return (int(major), int(minor), int(patch), tail)


def is_release(version):
    """True for versions built from a tag (not a developer build)."""
    v = parse_version(version)
    return v is not None and "dev" not in (version or "")


def newer(candidate, current):
    a, b = parse_version(candidate), parse_version(current)
    if a is None:
        return False
    return b is None or a > b


def notes_from_body(body, limit=8):
    """Bullet lines of the release text, without Markdown links/emphasis."""
    notes = []
    for line in (body or "").splitlines():
        line = line.strip()
        if line[:2] in ("- ", "* "):
            text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line[2:])
            text = re.sub(r"[*_`]", "", text).strip()
            if text:
                notes.append(text)
        if len(notes) >= limit:
            break
    return notes


def pick_release(releases, channel, current):
    """The release to offer (or None): newest fitting the channel, newer than current, with a bundle."""
    best = None
    cur = parse_version(current)
    on_beta = channel == "beta" or bool(cur and len(cur[3]) > 1 and is_release(current))
    for r in releases:
        if r.get("draft"):
            continue
        if r.get("prerelease") and not on_beta:
            continue
        version = (r.get("tag_name") or "").lstrip("v")
        bundle = next((a for a in r.get("assets", []) if a.get("name", "").endswith(".raucb")), None)
        if not bundle or parse_version(version) is None or not newer(version, current):
            continue
        if best is None or parse_version(version) > parse_version(best["version"]):
            best = {"version": version, "notes": notes_from_body(r.get("body")),
                    "url": bundle["browser_download_url"], "size": bundle.get("size", 0),
                    "page": r.get("html_url")}
    return best


def auto_install_due(hour, playing, auto, current):
    """Automatic updates: at night (3–5 h), not while music plays, only on release builds."""
    return auto and not playing and 3 <= hour < 5 and is_release(current)


RAUC_PROGRESS = re.compile(r"^\s*(\d{1,3})%")


def rauc_progress(line):
    """'  40% Copying image to rootfs.1' -> 40"""
    m = RAUC_PROGRESS.match(line)
    return min(100, int(m.group(1))) if m else None
