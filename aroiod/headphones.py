"""Headphone correction filters from github.com/AcrosonusMastering/Headphone-Correction-Filters.

The project publishes one stereo WAV (48 kHz, minimum phase) per headphone model, made
from Rtings measurements (filters GPLv3 by Acrosonus Mastering, stated in its README).
Nothing of it is shipped: the Aroio lists the repository and downloads a filter from
GitHub only when someone applies it, so new headphones appear without an update.

Only 48 kHz exists. So that music keeps its rate (no resampling to 48 kHz), the filter is
redesigned for 44.1 to 192 kHz: same magnitude response up to 20 kHz (held above),
minimum phase like the original. The files end in long runs of zeros; they are trimmed.
"""

import math
import re
from urllib.parse import quote

import numpy as np

from . import dsp

REPO = "AcrosonusMastering/Headphone-Correction-Filters"
BRANCH = "main"
PAGE = f"https://github.com/{REPO}"
TREE_URL = f"https://api.github.com/repos/{REPO}/git/trees/{BRANCH}?recursive=1"
RAW_URL = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/" + "{path}"
COLLECTIONS = [
    ("Headphones_Convolutions", "Rtings (aktuell)"),
    ("Headphone_Old_Target_Curve_Response", "Harman (älter)"),
]
RATES = (44100, 48000, 88200, 96000, 176400, 192000)
SOURCE_RATE = 48000
MAX_BYTES = 8 * 1024 * 1024


def display_name(path):
    """"Headphones_Convolutions/AKG_K701-filters-48k (2).wav" -> "AKG K701"."""
    name = path.rsplit("/", 1)[-1]
    name = re.sub(r"\.wav$", "", name, flags=re.I)
    name = re.sub(r"\s*\(\d+\)$", "", name)
    name = re.sub(r"[-_ ]*filters?[-_ ]*\d+k$", "", name, flags=re.I)
    name = re.sub(r"_+", " ", name)
    return re.sub(r"\s+", " ", name).strip(" -")


def parse_tree(tree):
    """GitHub tree listing -> [{"id", "label", "items": [{"path", "name"}]}]."""
    paths = [e["path"] for e in tree.get("tree", []) if e.get("type") == "blob"]
    out = []
    for cid, label in COLLECTIONS:
        items = [{"path": p, "name": display_name(p)} for p in paths
                 if p.startswith(cid + "/") and p.lower().endswith(".wav") and p.count("/") == 1]
        items.sort(key=lambda i: i["name"].casefold())
        if items:
            out.append({"id": cid, "label": label, "items": items})
    return out


def raw_url(path):
    return RAW_URL.format(path=quote(path))


def trim(taps, rel=1e-10, minimum=256):
    """Drop the tail that holds less than `rel` of the energy (power-of-two length)."""
    e = np.cumsum(taps[::-1] ** 2)[::-1]
    total = e[0] if len(e) else 0.0
    if total <= 0:
        return taps[:minimum]
    keep = int(np.argmax(e <= rel * total)) or len(taps)
    n = max(minimum, 1 << math.ceil(math.log2(max(keep, 1))))
    return taps[:n]


def _minimum_phase(mag, n):
    """Minimum-phase impulse response of length n for |H| on the rfft grid of n (cepstrum)."""
    cep = np.fft.irfft(np.log(np.maximum(mag, 1e-9)), n)
    fold = np.zeros(n)
    fold[0] = 1.0
    fold[1:n // 2] = 2.0
    fold[n // 2] = 1.0
    return np.fft.irfft(np.exp(np.fft.rfft(cep * fold, n)), n)


def for_rate(taps, rate, source_rate=SOURCE_RATE, n_source=65536):
    """The 48 kHz filter for another rate: same magnitude up to 20 kHz, held above."""
    if rate == source_rate:
        return trim(taps)
    spec = np.abs(np.fft.rfft(taps, n_source))
    f_src = np.fft.rfftfreq(n_source, 1 / source_rate)
    n = 1 << math.ceil(math.log2(n_source * rate / source_rate))
    f = np.fft.rfftfreq(n, 1 / rate)
    db = 20 * np.log10(np.maximum(spec, 1e-9))
    top = float(np.interp(20000.0, f_src, db))
    target = np.where(f <= 20000.0, np.interp(np.minimum(f, 20000.0), f_src, db), top)
    return trim(_minimum_phase(10 ** (target / 20), n))


def build(data):
    """WAV bytes -> ({rate: {"L": taps, "R": taps}}, peak gain in dB)."""
    rate, frames = dsp.read_wav_frames(data)
    if rate != SOURCE_RATE:
        raise dsp.FilterFileError(f"Filter hat {rate} Hz, erwartet sind {SOURCE_RATE} Hz")
    left = frames[:, 0]
    right = frames[:, 1] if frames.shape[1] > 1 else left
    out, peak = {}, -120.0
    for r in RATES:
        pair = {"L": for_rate(left, r), "R": for_rate(right, r)}
        for t in pair.values():
            if not np.all(np.isfinite(t)):
                raise dsp.FilterFileError("Filter enthält ungültige Werte")
            peak = max(peak, dsp.fir_peak_db(t))
        out[r] = pair
    return out, peak
