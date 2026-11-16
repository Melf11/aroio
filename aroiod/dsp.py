"""DSP: presets -> CamillaDSP 4 configuration, and filter responses for charts.

The CamillaDSP config is emitted as JSON (valid YAML 1.2, accepted by
CamillaDSP). Signal flow, identical to the old BruteFIR setup:

    capture (Loopback, source rate) -> preset gain/delay -> PEQ or FIR per
    channel -> optional M/S matrix ("Cleaner") -> playback (DAC)

M/S as in aroio-ng brutefir.conf.default.jack.mscoded:
    out_L = 0.5*L + 0.5*R   (mid)
    out_R = 0.5*L - 0.5*R   (side)

With the bypass preset and no Cleaner the pipeline is empty, so samples pass
unchanged (S32 -> f64 -> S32 is lossless): bit-perfect.
"""

import math
import struct
from pathlib import Path

import numpy as np

CH = {"L": 0, "R": 1}
MS_GAIN_DB = 20 * math.log10(0.5)  # -6.0206 dB

BIQUAD_TYPES = {"peaking": "Peaking", "lowshelf": "Lowshelf", "highshelf": "Highshelf",
                "lowpass": "Lowpass", "highpass": "Highpass"}


def camilla_config(preset, rate, *, ms_cleaner=False, fir_dir="/data/filters",
                   capture="hw:Loopback,1", playback="hw:0,0", chunksize=None,
                   target_level=None, resampler=None, capture_rate=None, release_capture=False,
                   capture_format="S32_LE"):
    """Return the CamillaDSP config dict for one preset at one sample rate.

    rate          processing/playback rate
    capture_rate  rate of the source if different (fixed-rate mode, resampler on)
    release_capture  stop when no player has the loopback open (device): the next
                  player opens it at its own rate, aroiod then restarts CamillaDSP
                  at exactly that rate (real.LoopbackWatch)
    """
    chunk = chunksize or default_chunksize(rate)
    devices = {
        "samplerate": rate,
        "chunksize": chunk,
        "target_level": target_level or chunk * 2,
        "enable_rate_adjust": True,
        "stop_on_rate_change": capture_rate is None,
        "rate_measure_interval": 1.0,
        "volume_ramp_time": 150,
        "capture": {"type": "Alsa", "channels": 2, "device": capture, "format": capture_format,
                    **({"stop_on_inactive": True} if release_capture else {})},
        "playback": {"type": "Alsa", "channels": 2, "device": playback, "format": "S32_LE"},
    }
    if capture_rate and capture_rate != rate:
        devices["capture_samplerate"] = capture_rate
        devices["resampler"] = {"type": "AsyncSinc", "profile": {
            "fast": "Fast", "balanced": "Balanced", "best": "Accurate"}[resampler or "balanced"]}

    filters, mixers, pipeline = {}, {}, []
    per_ch = {"L": [], "R": []}

    gain = float(preset.get("gain_db", 0.0))
    if gain:
        filters["preset_gain"] = {"type": "Gain", "parameters": {"gain": gain, "scale": "dB"}}
        per_ch["L"].append("preset_gain")
        per_ch["R"].append("preset_gain")

    for ch in ("L", "R"):
        trim = float((preset.get("trim_db") or {}).get(ch, 0.0))
        if trim:
            name = f"trim_{ch}"
            filters[name] = {"type": "Gain", "parameters": {"gain": trim, "scale": "dB"}}
            per_ch[ch].append(name)
        delay = float((preset.get("delay_ms") or {}).get(ch, 0.0))
        if delay:
            name = f"delay_{ch}"
            filters[name] = {"type": "Delay", "parameters": {"delay": delay, "unit": "ms", "subsample": True}}
            per_ch[ch].append(name)

    kind = preset.get("kind")
    if kind == "peq":
        for ch in ("L", "R"):
            for i, f in enumerate((preset.get("peq") or {}).get(ch, [])):
                name = f"peq_{ch}_{i}"
                params = {"type": BIQUAD_TYPES[f["type"]], "freq": f["freq"]}
                if f["type"] in ("peaking", "lowshelf", "highshelf"):
                    params["gain"] = f["gain"]
                params["q"] = f["q"]
                filters[name] = {"type": "Biquad", "parameters": params}
                per_ch[ch].append(name)
    elif kind == "fir":
        files = (preset.get("fir") or {}).get(str(rate))
        if not files:
            raise MissingRate(rate)
        for ch in ("L", "R"):
            name = f"fir_{ch}"
            filters[name] = {"type": "Conv", "parameters": {
                "type": "Raw", "filename": str(Path(fir_dir) / files[ch]), "format": "F64_LE"}}
            per_ch[ch].append(name)

    for ch in ("L", "R"):
        if per_ch[ch]:
            pipeline.append({"type": "Filter", "channels": [CH[ch]], "names": per_ch[ch]})

    if ms_cleaner:
        mixers["cleaner"] = {"channels": {"in": 2, "out": 2}, "mapping": [
            {"dest": 0, "sources": [{"channel": 0, "gain": MS_GAIN_DB, "inverted": False},
                                    {"channel": 1, "gain": MS_GAIN_DB, "inverted": False}]},
            {"dest": 1, "sources": [{"channel": 0, "gain": MS_GAIN_DB, "inverted": False},
                                    {"channel": 1, "gain": MS_GAIN_DB, "inverted": True}]},
        ]}
        pipeline.append({"type": "Mixer", "name": "cleaner"})

    return {"description": f"Aroio preset {preset.get('id')} @ {rate} Hz",
            "devices": devices, "filters": filters, "mixers": mixers, "pipeline": pipeline}


class MissingRate(Exception):
    def __init__(self, rate):
        super().__init__(f"No FIR filter for {rate} Hz")
        self.rate = rate


def default_chunksize(rate):
    # ~21 ms at every rate; measured defaults replace this in phase 1
    return 1024 * max(1, round(rate / 48000))


def is_bit_perfect(cfg):
    return not cfg["pipeline"] and "capture_samplerate" not in cfg["devices"]


# ── Filter responses (charts, room correction) ────────────────────────────────

def biquad_coeffs(f, rate):
    """RBJ Audio EQ Cookbook coefficients (b0,b1,b2,a0,a1,a2)."""
    w0 = 2 * math.pi * f["freq"] / rate
    cw, sw = math.cos(w0), math.sin(w0)
    alpha = sw / (2 * f["q"])
    A = 10 ** (f.get("gain", 0.0) / 40)
    t = f["type"]
    if t == "peaking":
        b = (1 + alpha * A, -2 * cw, 1 - alpha * A)
        a = (1 + alpha / A, -2 * cw, 1 - alpha / A)
    elif t in ("lowshelf", "highshelf"):
        sq = 2 * math.sqrt(A) * alpha
        if t == "lowshelf":
            b = (A * ((A + 1) - (A - 1) * cw + sq), 2 * A * ((A - 1) - (A + 1) * cw), A * ((A + 1) - (A - 1) * cw - sq))
            a = ((A + 1) + (A - 1) * cw + sq, -2 * ((A - 1) + (A + 1) * cw), (A + 1) + (A - 1) * cw - sq)
        else:
            b = (A * ((A + 1) + (A - 1) * cw + sq), -2 * A * ((A - 1) + (A + 1) * cw), A * ((A + 1) + (A - 1) * cw - sq))
            a = ((A + 1) - (A - 1) * cw + sq, 2 * ((A - 1) - (A + 1) * cw), (A + 1) - (A - 1) * cw - sq)
    elif t == "lowpass":
        b = ((1 - cw) / 2, 1 - cw, (1 - cw) / 2)
        a = (1 + alpha, -2 * cw, 1 - alpha)
    elif t == "highpass":
        b = ((1 + cw) / 2, -(1 + cw), (1 + cw) / 2)
        a = (1 + alpha, -2 * cw, 1 - alpha)
    else:
        raise ValueError(t)
    return b, a


def biquad_response_db(filters, freqs, rate=48000):
    freqs = np.asarray(freqs, dtype=float)
    z = np.exp(-1j * 2 * np.pi * freqs / rate)
    total = np.zeros_like(freqs)
    for f in filters:
        b, a = biquad_coeffs(f, rate)
        h = (b[0] + b[1] * z + b[2] * z * z) / (a[0] + a[1] * z + a[2] * z * z)
        total += 20 * np.log10(np.maximum(np.abs(h), 1e-12))
    return total


def log_freqs(n=96, lo=20.0, hi=20000.0):
    return np.geomspace(lo, hi, n)


def headroom_db(peq, rate=48000):
    """Pre-gain that keeps a PEQ preset from clipping: minus the largest boost of
    any channel (0 if the filters only cut)."""
    freqs = log_freqs(400, 10.0, 22000.0)
    peak = max((float(np.max(biquad_response_db(f, freqs, rate))) for f in (peq or {}).values() if f), default=0.0)
    return round(-max(0.0, peak), 1)


def loudness_db(preset, rate=48000, fir_dir="/data/filters"):
    """Level of the preset as heard with music: the filter response (plus pre-gain and
    trims) averaged as power over 50 Hz-12 kHz with equal weight per octave (pink, like
    music's spectrum). The A/B comparison plays "without correction" at this level, so
    the two differ in sound only, not in loudness (louder simply sounds "better")."""
    freqs = log_freqs(200, 50.0, 12000.0)
    kind, per_ch = preset.get("kind"), []
    for ch in ("L", "R"):
        if kind == "peq":
            r = np.asarray(biquad_response_db((preset.get("peq") or {}).get(ch, []), freqs, rate), dtype=float)
        elif kind == "fir":
            name = ((preset.get("fir") or {}).get(str(rate)) or {}).get(ch)
            path = Path(fir_dir) / name if name else None
            r = (np.asarray(fir_response_db(np.fromfile(path, dtype="<f8"), freqs, rate))
                 if path and path.exists() else np.zeros(len(freqs)))
        else:
            r = np.zeros(len(freqs))
        r = r + float(preset.get("gain_db", 0.0)) + float((preset.get("trim_db") or {}).get(ch, 0.0))
        per_ch.append(10 * np.log10(np.mean(10 ** (r / 10))))
    return round(float(10 * np.log10(np.mean(10 ** (np.asarray(per_ch) / 10)))), 1)


# ── FIR files (Acourate .dbl = raw FLOAT64LE, or WAV) ─────────────────────────

class FilterFileError(ValueError):
    pass


def read_fir(data, name):
    """Parse an uploaded FIR file. Returns numpy float64 taps."""
    lower = name.lower()
    if lower.endswith(".dbl"):
        if len(data) % 8 or not data:
            raise FilterFileError("Datei ist keine gültige .dbl-Datei (Länge kein Vielfaches von 8 Byte)")
        taps = np.frombuffer(data, dtype="<f8")
    elif lower.endswith(".wav"):
        taps = _read_wav(data)
    else:
        raise FilterFileError("Nur .dbl- oder .wav-Dateien")
    if not np.all(np.isfinite(taps)):
        raise FilterFileError("Datei enthält ungültige Werte")
    if len(taps) > 1_048_576:
        raise FilterFileError("Filter ist zu lang (mehr als 1 048 576 Taps)")
    return taps


def _read_wav(data):
    rate, frames = read_wav_frames(data)
    if frames.shape[1] != 1:
        raise FilterFileError("WAV-Filter muss mono sein (eine Datei pro Kanal)")
    return frames[:, 0]


def read_wav_frames(data):
    """WAV bytes -> (rate, float64 array of shape (frames, channels))."""
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise FilterFileError("Keine WAV-Datei")
    pos, fmt, raw = 12, None, None
    while pos + 8 <= len(data):
        cid, size = data[pos:pos + 4], struct.unpack("<I", data[pos + 4:pos + 8])[0]
        body = data[pos + 8:pos + 8 + size]
        if cid == b"fmt ":
            fmt = struct.unpack("<HHIIHH", body[:16])
        elif cid == b"data":
            raw = body
        pos += 8 + size + (size & 1)
    if not fmt or raw is None:
        raise FilterFileError("WAV-Datei unvollständig")
    tag, channels, rate, _, _, bits = fmt
    if tag == 0xFFFE and len(body := _chunk(data, b"fmt ")) >= 26:     # WAVE_FORMAT_EXTENSIBLE
        tag = struct.unpack("<H", body[24:26])[0]
    if not channels:
        raise FilterFileError("WAV-Datei ohne Kanäle")
    if tag == 3 and bits == 64:
        v = np.frombuffer(raw, dtype="<f8").astype(np.float64)
    elif tag == 3 and bits == 32:
        v = np.frombuffer(raw, dtype="<f4").astype(np.float64)
    elif tag == 1 and bits == 32:
        v = np.frombuffer(raw, dtype="<i4").astype(np.float64) / 2 ** 31
    elif tag == 1 and bits == 24:
        b = np.frombuffer(raw[:len(raw) // 3 * 3], dtype=np.uint8).reshape(-1, 3)
        v = (b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8) | (b[:, 2].astype(np.int32) << 16))
        v = np.where(v & 0x800000, v - 0x1000000, v).astype(np.float64) / 2 ** 23
    elif tag == 1 and bits == 16:
        v = np.frombuffer(raw[:len(raw) // 2 * 2], dtype="<i2").astype(np.float64) / 2 ** 15
    else:
        raise FilterFileError("WAV-Format wird nicht unterstützt")
    v = v[:len(v) // channels * channels]
    return rate, v.reshape(-1, channels)


def _chunk(data, cid):
    pos = 12
    while pos + 8 <= len(data):
        c, size = data[pos:pos + 4], struct.unpack("<I", data[pos + 4:pos + 8])[0]
        if c == cid:
            return data[pos + 8:pos + 8 + size]
        pos += 8 + size + (size & 1)
    return b""


def fir_response_db(taps, freqs, rate):
    n = max(65536, 1 << int(math.ceil(math.log2(len(taps)))))
    spec = np.fft.rfft(taps, n)
    bins = np.fft.rfftfreq(n, 1 / rate)
    mag = 20 * np.log10(np.maximum(np.abs(spec), 1e-12))
    return np.interp(freqs, bins, mag)


def fir_peak_db(taps):
    return float(20 * np.log10(max(np.max(np.abs(np.fft.rfft(taps, 65536))), 1e-12)))
