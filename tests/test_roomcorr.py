import numpy as np
import pytest

from aroiod import dsp
from aroiod import roomcorr as rc


@pytest.fixture(scope="module")
def measured():
    rate = 48000
    sweep, inverse = rc.log_sweep(rate, seconds=2)
    room = rc.SimRoom(rate)
    curves, peaks = {}, {}
    for ch in "LR":
        cs = []
        for pos in range(3):
            ir, peak = rc.impulse_response(room.record(sweep, ch, pos), inverse)
            f, db = rc.magnitude(ir, peak, rate)
            freqs, s = rc.smooth(f, db, 6)
            cs.append(s)
            peaks[(ch, pos)] = peak
        curves[ch] = rc.average(cs)
    return freqs, curves, peaks


def test_correction_improves_and_stays_safe(measured):
    freqs, curves, _ = measured
    out = rc.correct(curves, "neutral", freqs=freqs)
    for ch, c in out["channels"].items():
        assert c["deviation_after"] < c["deviation_before"]
        assert len(c["filters"]) <= rc.MAX_FILTERS
        eq = dsp.biquad_response_db(c["filters"], freqs)
        assert eq.max() <= rc.MAX_BOOST + 0.3           # total boost limited
        assert all(f["freq"] <= 600 for f in c["filters"])
    # the strongest room mode (42 Hz, +9 dB) gets cut
    cuts = [f for f in out["channels"]["L"]["filters"] if f["gain"] < -3]
    assert any(35 < f["freq"] < 50 for f in cuts)


def test_no_boost_below_speaker_rolloff(measured):
    freqs, curves, _ = measured
    target = rc.target_curve(freqs)
    aligned = curves["L"] - rc.level_at(freqs, curves["L"])
    low = rc.speaker_low_limit(freqs, aligned, target)
    assert 25 < low < 45                                # sim speaker: 38 Hz high-pass
    filters, _ = rc.fit_peq(freqs, aligned, target)
    assert not any(f["gain"] > 0 and f["freq"] < low for f in filters)


def test_level_and_time_alignment(measured):
    freqs, curves, peaks = measured
    out = rc.correct(curves, "neutral", freqs=freqs)
    assert out["trim_db"]["R"] == 0.0 and out["trim_db"]["L"] < 0     # R is quieter, L is turned down
    diff_ms = (peaks[("R", 0)] - peaks[("L", 0)]) * 1000 / 48000
    assert diff_ms == pytest.approx(0.12 / 343 * 1000, abs=0.05)         # 12 cm further away


def test_characters_differ():
    f = np.geomspace(20, 20000, 50)
    warm, bright = rc.target_curve(f, "warm"), rc.target_curve(f, "bright")
    assert warm[0] > bright[0] and warm[-1] < bright[-1]


def test_calibration_file():
    text = '"Sens Factor =-1.378dB, SERNO: 7004512"\n10.054 -3.2\n20.0 -1.1\n' + "\n".join(
        f"{f} 0.0" for f in range(100, 20000, 1000))
    serial, pairs = rc.parse_calibration(text)
    assert serial == "7004512" and pairs[0] == (10.054, -3.2)
    with pytest.raises(ValueError):
        rc.parse_calibration("nothing here")
