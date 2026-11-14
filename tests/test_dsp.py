import struct

import numpy as np
import pytest

from aroiod import dsp
from aroiod.config import builtin_bypass


def test_bypass_is_bit_perfect():
    cfg = dsp.camilla_config(builtin_bypass(), 96000)
    assert cfg["pipeline"] == [] and dsp.is_bit_perfect(cfg)
    assert cfg["devices"]["samplerate"] == 96000
    assert cfg["devices"]["stop_on_rate_change"] is True


def test_cleaner_matrix_matches_old_brutefir():
    cfg = dsp.camilla_config(builtin_bypass(), 48000, ms_cleaner=True)
    m = cfg["mixers"]["cleaner"]["mapping"]
    assert [s["inverted"] for s in m[1]["sources"]] == [False, True]
    assert all(abs(s["gain"] + 6.0206) < 1e-3 for row in m for s in row["sources"])
    assert not dsp.is_bit_perfect(cfg)


def test_peq_fir_and_resampling():
    peq = {"id": "p", "kind": "peq", "gain_db": -3, "trim_db": {"L": -1, "R": 0}, "delay_ms": {"L": 0, "R": 0.5},
           "peq": {"L": [{"type": "peaking", "freq": 50, "gain": -6, "q": 3}], "R": []}}
    cfg = dsp.camilla_config(peq, 44100)
    names = {s["channels"][0]: s["names"] for s in cfg["pipeline"]}
    assert names[0] == ["preset_gain", "trim_L", "peq_L_0"]
    assert names[1] == ["preset_gain", "delay_R"]
    fir = {"id": "f", "kind": "fir", "fir": {"96000": {"L": "a.dbl", "R": "b.dbl"}}}
    with pytest.raises(dsp.MissingRate):
        dsp.camilla_config(fir, 44100)
    cfg = dsp.camilla_config(fir, 96000, capture_rate=44100, resampler="best", fir_dir="/data/filters")
    assert cfg["devices"]["capture_samplerate"] == 44100
    assert cfg["devices"]["resampler"]["profile"] == "VeryAccurate"
    assert cfg["filters"]["fir_L"]["parameters"]["filename"] == "/data/filters/a.dbl"


def test_biquad_response_peaks_at_freq():
    f = np.array([20.0, 100.0, 1000.0])
    db = dsp.biquad_response_db([{"type": "peaking", "freq": 100, "gain": -6, "q": 2}], f)
    assert db[1] == pytest.approx(-6, abs=0.05)
    assert abs(db[2]) < 0.2


def test_read_fir_formats():
    taps = np.array([0.0, 1.0, 0.5, -0.25])
    assert np.allclose(dsp.read_fir(taps.astype("<f8").tobytes(), "x.dbl"), taps)
    raw = taps.astype("<f4").tobytes()
    wav = (b"RIFF" + struct.pack("<I", 36 + len(raw)) + b"WAVE" + b"fmt " + struct.pack("<IHHIIHH", 16, 3, 1, 48000, 192000, 4, 32)
           + b"data" + struct.pack("<I", len(raw)) + raw)
    assert np.allclose(dsp.read_fir(wav, "x.wav"), taps)
    with pytest.raises(dsp.FilterFileError):
        dsp.read_fir(b"123", "x.dbl")
    with pytest.raises(dsp.FilterFileError):
        dsp.read_fir(np.array([np.nan]).tobytes(), "x.dbl")
