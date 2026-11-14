"""Room correction: measurement maths and automatic PEQ.

    sweep -> recording -> impulse response -> windowed magnitude response
    -> mic calibration -> fractional-octave smoothing -> average of positions
    -> target curve (character) -> PEQ fit (mostly cuts, small boosts)

Kept conservative on purpose, the audience is not technical:
- correction only below `fmax` (default 500 Hz) where the room dominates
- boosts limited to +3 dB and only for broad dips (narrow nulls can't be filled)
- at most 10 filters per channel
"""

import math

import numpy as np


def fftconvolve(a, b):
    """Linear convolution via FFT (what scipy.signal.fftconvolve does, numpy only)."""
    n = len(a) + len(b) - 1
    size = 1 << int(math.ceil(math.log2(max(n, 1))))
    return np.fft.irfft(np.fft.rfft(a, size) * np.fft.rfft(b, size), size)[:n]


def least_squares(fun, x0, lo, hi, max_iter=40):
    """Bounded Levenberg-Marquardt (projected onto the bounds) with a numerical
    Jacobian: enough for fitting a handful of PEQ filters, no scipy needed."""
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    x = np.clip(np.asarray(x0, float), lo, hi)
    r = fun(x)
    cost, lam = float(r @ r), 1e-3
    for _ in range(max_iter):
        J = np.empty((len(r), len(x)))
        for i in range(len(x)):
            h = 1e-6 * max(1.0, abs(x[i]))
            xi = x.copy()
            xi[i] = x[i] + h if x[i] + h <= hi[i] else x[i] - h
            J[:, i] = (fun(xi) - r) / (xi[i] - x[i])
        g, A = J.T @ r, J.T @ J
        d = np.diag(A) + 1e-12
        improved = False
        while lam < 1e10:
            step = np.linalg.solve(A + lam * np.diag(d), -g)
            xn = np.clip(x + step, lo, hi)
            rn = fun(xn)
            cn = float(rn @ rn)
            if cn < cost:
                done = cost - cn < 1e-10 * max(cost, 1e-12)
                x, r, cost, lam, improved = xn, rn, cn, max(lam / 3, 1e-12), True
                break
            lam *= 4
        if not improved or done:
            break
    return x


FMIN, FMAX_DEFAULT = 20.0, 500.0
MAX_BOOST, MAX_CUT = 3.0, -15.0
MAX_FILTERS = 10

# house curves relative to 1 kHz: (bass shelf dB, shelf corner Hz, tilt dB/octave above 1 kHz)
CHARACTERS = {
    "neutral": (3.0, 120.0, -0.5),
    "warm": (5.0, 150.0, -1.0),
    "bright": (2.0, 100.0, 0.0),
}


# ── Signals ──────────────────────────────────────────────────────────────────

def log_sweep(rate, seconds=8.0, f1=10.0, f2=None, level_db=-12.0):
    """Exponential sine sweep (Farina) and its inverse filter."""
    f2 = f2 or min(22000.0, rate / 2 * 0.95)
    n = int(seconds * rate)
    t = np.arange(n) / rate
    k = math.log(f2 / f1)
    sweep = np.sin(2 * math.pi * f1 * seconds / k * (np.exp(t * k / seconds) - 1))
    fade = int(0.05 * rate)
    win = np.ones(n)
    win[:fade] = np.hanning(2 * fade)[:fade]
    win[-fade:] = np.hanning(2 * fade)[fade:]
    sweep *= win * 10 ** (level_db / 20)
    inverse = sweep[::-1] * np.exp(-t * k / seconds)
    inverse /= np.abs(np.fft.rfft(fftconvolve(sweep, inverse))).max()
    return sweep, inverse


def write_wav_f32(path, data, rate=48000):
    """Mono 32-bit float WAV (format 3): what Acourate and REW import without loss."""
    import struct
    raw = np.asarray(data, dtype="<f4").tobytes()
    header = struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + len(raw), b"WAVE", b"fmt ", 16, 3, 1, rate,
                         rate * 4, 4, 32, b"data", len(raw))
    with open(path, "wb") as fh:
        fh.write(header + raw)


def impulse_response(recording, inverse):
    ir = fftconvolve(recording, inverse)
    peak = int(np.argmax(np.abs(ir)))
    return ir, peak


def magnitude(ir, peak, rate, window_ms=500.0, pre_ms=5.0, nfft=None):
    """Magnitude response (dB) of the windowed IR around its peak."""
    pre, post = int(pre_ms * rate / 1000), int(window_ms * rate / 1000)
    start = max(0, peak - pre)
    seg = ir[start:peak + post].copy()
    w = np.ones(len(seg))
    fi = min(pre, peak - start)
    if fi > 0:
        w[:fi] = np.hanning(2 * fi)[:fi]
    fo = len(seg) // 4
    w[-fo:] = np.hanning(2 * fo)[fo:]
    seg *= w
    nfft = nfft or 1 << int(math.ceil(math.log2(max(len(seg), rate // 2))))
    spec = np.fft.rfft(seg, nfft)
    freqs = np.fft.rfftfreq(nfft, 1 / rate)
    return freqs, 20 * np.log10(np.maximum(np.abs(spec), 1e-12))


def smooth(freqs, db, fraction=6, out=None):
    """Fractional-octave smoothing (power average), sampled at `out`."""
    out = np.geomspace(FMIN, 20000.0, 240) if out is None else np.asarray(out)
    power = 10 ** (db / 10)
    res = np.empty(len(out))
    half = 2 ** (1 / (2 * fraction))
    cum = np.concatenate([[0.0], np.cumsum(power)])
    for i, f in enumerate(out):
        lo = np.searchsorted(freqs, f / half)
        hi = max(lo + 1, np.searchsorted(freqs, f * half))
        res[i] = (cum[hi] - cum[lo]) / (hi - lo)
    return out, 10 * np.log10(np.maximum(res, 1e-20))


def apply_calibration(freqs, db, calibration):
    """calibration: list of (freq, dB) pairs as in miniDSP .txt files."""
    if not calibration:
        return db
    cf = np.array([c[0] for c in calibration], dtype=float)
    cd = np.array([c[1] for c in calibration], dtype=float)
    return db - np.interp(freqs, cf, cd)


def parse_calibration(text):
    """Parse a miniDSP / REW calibration file. Returns (serial or None, pairs)."""
    pairs, serial = [], None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(('"', "*", "#")) or line[0].isalpha():
            low = line.lower()
            if "sens" in low or "serial" in low or "umik" in low:
                digits = "".join(ch if ch.isdigit() or ch == "-" else " " for ch in line).split()
                serial = serial or next((d for d in digits if len(d) >= 6), None)
            continue
        parts = line.replace(",", " ").replace(";", " ").split()
        try:
            pairs.append((float(parts[0]), float(parts[1])))
        except (ValueError, IndexError):
            continue
    if len(pairs) < 10:
        raise ValueError("Kalibrierdatei enthält zu wenige Messpunkte")
    return serial, pairs


def average(curves):
    """Power average of several dB curves on the same frequency grid."""
    return 10 * np.log10(np.mean([10 ** (c / 10) for c in curves], axis=0))


def level_at(freqs, db, lo=500.0, hi=2000.0):
    m = (freqs >= lo) & (freqs <= hi)
    return float(np.mean(db[m]))


def arrival_ms(peak, rate):
    return peak * 1000.0 / rate


# ── Target and fit ───────────────────────────────────────────────────────────

def target_curve(freqs, character="neutral"):
    shelf, corner, tilt = CHARACTERS[character]
    freqs = np.asarray(freqs, dtype=float)
    bass = shelf / (1 + (freqs / corner) ** 2)
    treble = np.where(freqs > 1000, tilt * np.log2(np.maximum(freqs, 1) / 1000), 0.0)
    return bass + treble


def _peq_db(params, freqs, rate):
    from .dsp import biquad_response_db
    return biquad_response_db(params_to_filters(params), freqs, rate)


def params_to_filters(params):
    return [{"type": "peaking", "freq": float(params[i]), "gain": float(params[i + 1]),
             "q": float(params[i + 2])} for i in range(0, len(params), 3)]


def fit_peq(freqs, measured, target, fmax=FMAX_DEFAULT, max_filters=MAX_FILTERS,
            rate=48000, tolerance=1.0):
    """Greedy placement + joint least-squares refinement.

    Returns (filters, corrected_curve). `measured` and `target` are dB on the
    `freqs` grid and must already be level-aligned.
    """
    freqs = np.asarray(freqs, dtype=float)
    f_low = speaker_low_limit(freqs, measured, target)
    band = (freqs >= f_low) & (freqs <= fmax)
    f_band = freqs[band]
    error = measured[band] - target[band]
    params, lo, hi = [], [], []
    ignored = np.zeros(len(f_band), dtype=bool)   # narrow dips nobody can fill

    def residual(p):
        eq = _peq_db(p, f_band, rate) if len(p) else np.zeros(len(f_band))
        e = np.where(ignored, 0.0, error + eq)
        # the sum of all filters must never boost more than MAX_BOOST
        over = np.maximum(0.0, eq - MAX_BOOST) * 10
        return np.concatenate([np.where(e > 0, e, e * 0.6), over])

    for _ in range(max_filters * 4):
        if len(params) // 3 >= max_filters:
            break
        eq = _peq_db(params, f_band, rate) if params else np.zeros(len(f_band))
        e = np.where(ignored, 0.0, error + eq)
        idx = int(np.argmax(np.abs(e)))
        if abs(e[idx]) < tolerance:
            break
        gain = float(np.clip(-e[idx], MAX_CUT, MAX_BOOST - max(0.0, eq[idx])))
        if gain > 0 and (_is_narrow(f_band, e, idx) or gain < 0.5):
            ignored |= _region(f_band, idx, 1 / 6)
            continue
        if any(abs(math.log2(f_band[idx] / params[i])) < 1 / 6 and np.sign(params[i + 1]) == np.sign(gain)
               for i in range(0, len(params), 3)):
            ignored |= _region(f_band, idx, 1 / 12)   # already covered, let the refinement handle it
            continue
        q = _estimate_q(f_band, e, idx)
        if gain > 0:
            params += [float(f_band[idx]), gain, min(q, 2.0)]
            lo += [f_low, 0.0, 0.5]
            hi += [fmax, MAX_BOOST, 2.0]
        else:
            params += [float(f_band[idx]), gain, q]
            lo += [f_low, MAX_CUT, 0.5]
            hi += [fmax * 1.2, 0.0, 6.0]
        p0 = np.clip(params, lo, hi)
        params = list(least_squares(residual, p0, lo, hi))

    filters = params_to_filters(params) if params else []
    filters = [f for f in filters if abs(f["gain"]) >= 0.5]
    filters = limit_boost(filters, freqs, rate)
    for f in filters:
        f["freq"] = round(f["freq"], 1)
        f["gain"] = round(f["gain"], 1)
        f["q"] = round(f["q"], 2)
    from .dsp import biquad_response_db
    corrected = measured + biquad_response_db(filters, freqs, rate)
    return sorted(filters, key=lambda f: f["freq"]), corrected


def limit_boost(filters, freqs, rate=48000, limit=MAX_BOOST):
    """Hard guarantee: the combined response never exceeds `limit` dB. Overlapping
    boosts are scaled down together until it fits."""
    from .dsp import biquad_response_db
    for _ in range(20):
        peak = float(np.max(biquad_response_db(filters, freqs, rate))) if filters else 0.0
        if peak <= limit + 0.05:
            break
        scale = max(0.0, 1 - (peak - limit) / max(peak, 1e-6) - 0.02)
        filters = [dict(f, gain=f["gain"] * scale) if f["gain"] > 0 else f for f in filters]
    return [f for f in filters if abs(f["gain"]) >= 0.3]


def _estimate_q(freqs, e, idx):
    half = abs(e[idx]) / 2
    lo = idx
    while lo > 0 and abs(e[lo]) > half and np.sign(e[lo]) == np.sign(e[idx]):
        lo -= 1
    hi = idx
    while hi < len(e) - 1 and abs(e[hi]) > half and np.sign(e[hi]) == np.sign(e[idx]):
        hi += 1
    bw_oct = max(math.log2(freqs[hi] / max(freqs[lo], 1e-6)), 0.1)
    q = math.sqrt(2 ** bw_oct) / (2 ** bw_oct - 1)
    return float(np.clip(q, 0.5, 6.0))


def _is_narrow(freqs, e, idx):
    return _estimate_q(freqs, e, idx) > 4.0


def _region(freqs, idx, octaves):
    f = freqs[idx]
    return (freqs >= f / 2 ** octaves) & (freqs <= f * 2 ** octaves)


def speaker_low_limit(freqs, measured, target):
    """Lowest frequency the speaker still reproduces (−6 dB re target, on a
    1-octave smoothed error). Below it nothing is boosted: pushing a speaker
    below its roll-off only costs headroom and excursion."""
    err = measured - target
    k = max(1, int(len(freqs) / np.log2(freqs[-1] / freqs[0])))   # points per octave
    padded = np.pad(err, (k // 2, k - 1 - k // 2), mode="edge")   # no zero padding at the edges
    smooth_err = np.convolve(padded, np.ones(k) / k, mode="valid")
    ok = np.nonzero(smooth_err > -6.0)[0]
    return float(max(FMIN, freqs[ok[0]])) if len(ok) else FMIN


def correct(curves_by_channel, character="neutral", fmax=FMAX_DEFAULT, rate=48000, freqs=None):
    """Full pipeline for already smoothed, averaged curves per channel.

    curves_by_channel: {"L": dB array, "R": dB array} on `freqs`
    Returns dict with filters per channel, trims, and curves for the chart.
    """
    freqs = np.geomspace(FMIN, 20000.0, 240) if freqs is None else np.asarray(freqs)
    levels = {ch: level_at(freqs, c) for ch, c in curves_by_channel.items()}
    ref = min(levels.values())
    out = {"freqs": freqs.tolist(), "channels": {}, "trim_db": {}}
    for ch, curve in curves_by_channel.items():
        trim = round(ref - levels[ch], 1)  # only attenuate the louder side
        aligned = curve - levels[ch]
        target = target_curve(freqs, character)
        filters, after = fit_peq(freqs, aligned, target, fmax=fmax, rate=rate)
        band = (freqs >= FMIN) & (freqs <= fmax)
        out["trim_db"][ch] = trim
        out["channels"][ch] = {
            "filters": filters,
            "before": np.round(aligned, 2).tolist(),
            "after": np.round(after, 2).tolist(),
            "target": np.round(target, 2).tolist(),
            "deviation_before": round(float(np.sqrt(np.mean((aligned[band] - target[band]) ** 2))), 2),
            "deviation_after": round(float(np.sqrt(np.mean((after[band] - target[band]) ** 2))), 2),
        }
    out["headroom_db"] = round(-max(0.0, max(
        (max((f["gain"] for f in c["filters"]), default=0.0) for c in out["channels"].values()), default=0.0)), 1)
    return out


# ── Simulated room (simulator + tests) ───────────────────────────────────────

class SimRoom:
    """A plausible living room: speaker roll-off, a few room modes, one
    reflection, noise. Deterministic for a given seed and position."""

    MODES = [(42.0, 9.0, 4.0), (68.0, -7.0, 6.0), (95.0, 6.0, 5.0), (140.0, -5.0, 3.0),
             (210.0, 4.0, 4.0), (330.0, -3.0, 2.5)]

    def __init__(self, rate=48000, seed=1):
        self.rate, self.seed = rate, seed

    def ir(self, channel, position):
        rate = self.rate
        rng = np.random.default_rng(self.seed * 1000 + position * 10 + (channel == "R"))
        n = int(0.6 * rate)
        h = np.zeros(n)
        dist_m = 2.8 + (0.12 if channel == "R" else 0.0) + 0.1 * position
        d = int(dist_m / 343.0 * rate)
        h[d] = 1.0
        h[d + int(0.004 * rate)] += 0.35 * (1 + 0.1 * position)    # floor reflection
        h[d + int(0.011 * rate)] -= 0.2
        # speaker (2nd order high-pass at 38 Hz) and room modes, applied in the
        # frequency domain (numpy only; long enough FFT so the decays do not wrap)
        from .dsp import biquad_coeffs
        size = 1 << int(math.ceil(math.log2(4 * n)))
        z = np.exp(-1j * 2 * np.pi * np.fft.rfftfreq(size))      # cycles per sample
        def resp(f):
            bq, aq = biquad_coeffs(f, rate)
            return (bq[0] + bq[1] * z + bq[2] * z * z) / (aq[0] + aq[1] * z + aq[2] * z * z)
        H = resp({"type": "highpass", "freq": 38.0, "q": 1 / math.sqrt(2)})
        for f, g, q in self.MODES:
            gain = g * (1 - 0.15 * position * rng.uniform(0.5, 1.0))
            H = H * resp({"type": "peaking", "freq": f, "gain": gain, "q": q})
        h = np.fft.irfft(np.fft.rfft(h, size) * H, size)[:n]
        h += rng.normal(0, 1e-5, n) * np.exp(-np.arange(n) / (0.15 * rate))
        if channel == "R":
            h *= 0.93  # right speaker a bit quieter
        return h

    def record(self, sweep, channel, position, noise_db=-75.0):
        rec = fftconvolve(sweep, self.ir(channel, position))
        rng = np.random.default_rng(self.seed + position)
        rec += rng.normal(0, 10 ** (noise_db / 20), len(rec))
        return rec
