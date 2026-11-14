from aroiod.config import Config
from aroiod.migration import SAMPLE_FILTERS, SAMPLE_USERCONFIG, migrate, parse_userconfig


def statuses(result):
    return {(i["area"], i["label"]): i for i in result["report"]}


def test_parse_is_safe_and_shell_like():
    u = parse_userconfig('A="x y"\nB=\'z\'\n# c\nexport C="1"\nrm -rf /\nD=$(reboot)\nlower="no"')
    assert u == {"A": "x y", "B": "z", "C": "1", "D": "$(reboot)"}


def test_sample_migrates_into_valid_config(tmp_path):
    result = migrate(SAMPLE_USERCONFIG, SAMPLE_FILTERS)
    c = Config(tmp_path / "c.json")
    c.patch(result["patch"])                        # must validate
    assert c.get("device.name") == "Aroio Wohnzimmer"
    assert c.get("network.hostname") == "Wohnzimmer"
    assert c.get("network.lan.dhcp") is False
    assert c.get("network.lan.address") == "192.168.1.50"
    assert c.get("dsp.ms_cleaner") is True
    assert c.get("sources.lms.enabled") and c.get("sources.airplay.enabled") and c.get("sources.spotify.enabled")
    assert c.get("sources.bluetooth.enabled") is False
    assert c.get("sources.lms.server") == "192.168.1.10"
    assert c.get("audio.rate_mode") == "follow"
    assert c.get("hardware.onboard_wifi") is False


def test_filter_banks_become_presets():
    result = migrate(SAMPLE_USERCONFIG, SAMPLE_FILTERS)
    presets = {p["id"]: p for p in result["patch"]["dsp"]["presets"]}
    assert set(presets) == {"bank0", "bank1"}
    assert presets["bank0"]["gain_db"] == -3.0
    assert set(presets["bank0"]["fir"]) == {"44100", "48000", "96000"}
    assert result["patch"]["dsp"]["active_preset"] == "bank0"
    # safe names, no spaces
    for c in result["copies"]:
        assert " " not in c["to"]
    assert {"from": "Abacus C-BoxL96.dbl", "to": "bank1_L_96000.dbl"} in result["copies"]
    rep = statuses(result)
    assert rep[("Klang", "Filterbank 2")]["status"] == "check"     # only 96 kHz


def test_legacy_names_and_hotspot():
    text = 'HOSTNAME="(none)"\nDHCP="OFF"\nIPADDR="10.0.0.5"\nNETMASK="255.0.0.0"\nGATEWAY="10.0.0.1"\nDNSSERV="10.0.0.1"\nWLANSSID="AroioAP"\n'
    result = migrate(text)
    assert result["patch"]["device"]["name"] == "AroioOS"
    assert result["patch"]["network"]["lan"]["address"] == "10.0.0.5"
    assert "wifi" not in result["patch"]["network"]


def test_netjack_dropped_and_missing_filters_reported():
    text = 'AUDIO_OUTPUT="jack-bf"\nBRUTEFIR="ON"\nJACKBF_NETJACK="ON"\nJACKBF_SQUEEZELITE="ON"\nCOEFF_NAME0="Raum"\nDEF_COEFF="0"\n'
    result = migrate(text, [])
    rep = statuses(result)
    assert rep[("Quellen", "NetJack")]["status"] == "check"
    assert rep[("Klang", "Filterbank 1: Raum")]["status"] == "check"
    assert "presets" not in result["patch"]["dsp"]


def test_secrets_not_in_patch():
    result = migrate('WLANSSID="Zuhause"\nWLANPWD="geheim123"\nUSERPASSWD="pw"\n')
    assert result["secrets"]["wifi.psk"] == "geheim123"
    assert "geheim123" not in str(result["patch"])
    assert result["patch"]["security"]["app_password"] is True
