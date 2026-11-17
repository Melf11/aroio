import json

import pytest

from aroiod.config import VERSION, Config, Invalid, default_config


def test_defaults_written_and_reloaded(tmp_path):
    path = tmp_path / "config.json"
    c = Config(path)
    assert c.get("device.name") == "Aroio"
    assert c.get("dsp.active_preset") == "bypass"
    assert json.loads(path.read_text())["version"] == VERSION
    assert Config(path).data == c.data


def test_patch_validates_and_keeps_old_on_error(tmp_path):
    c = Config(tmp_path / "c.json")
    c.patch({"device": {"name": "Wohnzimmer"}, "audio": {"start_volume": 40}})
    assert c.get("device.name") == "Wohnzimmer"
    with pytest.raises(Invalid) as exc:
        c.patch({"device": {"name": "Küche"}, "audio": {"start_volume": 400}})
    assert exc.value.path == "audio.start_volume"
    assert c.get("device.name") == "Wohnzimmer"          # nothing applied


@pytest.mark.parametrize("patch,field", [
    ({"device": {"unknown": 1}}, "device.unknown"),
    ({"network": {"hostname": "bad name!"}}, "network.hostname"),
    ({"network": {"lan": {"address": "300.1.1.1"}}}, "network.lan.address"),
    ({"audio": {"fixed_rate": 12345}}, "audio.fixed_rate"),
    ({"device": {"expert_mode": "yes"}}, "device.expert_mode"),
    ({"dsp": {"active_preset": "nope"}}, "dsp.active_preset"),
])
def test_rejects(tmp_path, patch, field):
    c = Config(tmp_path / "c.json")
    with pytest.raises(Invalid) as exc:
        c.patch(patch)
    assert exc.value.path == field


def test_presets_validated(tmp_path):
    c = Config(tmp_path / "c.json")
    good = {"id": "p1", "name": "Test", "kind": "peq",
            "peq": {"L": [{"type": "peaking", "freq": 50, "gain": -6, "q": 3}], "R": []}}
    c.patch({"dsp": {"presets": [good], "active_preset": "p1"}})
    ids = [p["id"] for p in c.get("dsp.presets")]
    assert ids == ["bypass", "p1"]                       # bypass always present
    with pytest.raises(Invalid):
        c.patch({"dsp": {"presets": [dict(good, peq={"L": [{"type": "peaking", "freq": 5, "gain": 0, "q": 1}]})]}})
    with pytest.raises(Invalid):
        c.patch({"dsp": {"presets": [dict(good, kind="fir", fir={"96000": {"L": "../etc/passwd", "R": "x.dbl"}})]}})


def test_broken_or_old_file_is_repaired(tmp_path):
    path = tmp_path / "c.json"
    cfg = default_config()
    del cfg["audio"]
    cfg["device"]["language"] = "klingonisch"
    cfg["stale"] = True
    path.write_text(json.dumps(cfg))
    c = Config(path)
    assert c.get("audio.rate_mode") == "follow"
    assert c.get("device.language") == "de"
    assert "stale" not in c.data
