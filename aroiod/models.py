"""Aroio hardware models and Raspberry Pi boards.

Taken from the old system (aroio-ng): aroio_gpio, index.php, audio.php.
- AroioLT: rotary encoder on GPIO 23/24, pause button on GPIO 27
- AroioEX: pause button on GPIO 27, fixed output level (VOLUME_START=0 dB)
- AroioSU: fixed output level (VOLUME_START=0 dB)
- RaspberryPi: AroioOS on a plain Pi with any supported DAC
The network LED sits on GPIO 22 (act-led overlay), IR receiver on GPIO 25.

The new system detects the model from the HAT EEPROM / DAC I2C id (phase 1).
The values below still need confirmation by Abacus (see docs/NEUBAU-PLAN.md).
"""

MODELS = {
    "AroioSU": {
        "label": "Aroio SU",
        "fixed_level": True,
        "encoder": None,
        "buttons": {},
        "has_input": False,
        "dac": "Aroio DAC",
    },
    "AroioEX": {
        "label": "Aroio EX",
        "fixed_level": True,
        "encoder": None,
        "buttons": {"play_pause": 27},
        "has_input": False,
        "dac": "Aroio DAC",
    },
    "AroioLT": {
        "label": "Aroio LT",
        "fixed_level": False,
        "encoder": {"a": 23, "b": 24},
        "buttons": {"play_pause": 27},
        "has_input": False,
        "dac": "Aroio DAC",
    },
    "RaspberryPi": {
        "label": "Raspberry Pi mit AroioOS",
        "fixed_level": False,
        "encoder": None,
        "buttons": {},
        "has_input": False,
        "dac": "automatisch",
    },
}

COMMON_PINS = {"led_network": 22, "ir": 25}

# Max FIR taps per channel the board handles at a given rate with a safety
# margin. Placeholder numbers, to be replaced by measurements in phase 0/1.
BOARDS = {
    "pi3b": {"label": "Raspberry Pi 3 B/B+", "cores": 4, "ram_mb": 1024,
             "fir_taps": {48000: 65536, 96000: 32768, 192000: 16384}},
    "pi4": {"label": "Raspberry Pi 4", "cores": 4, "ram_mb": 2048,
            "fir_taps": {48000: 262144, 96000: 131072, 192000: 65536}},
    "pi5": {"label": "Raspberry Pi 5", "cores": 4, "ram_mb": 4096,
            "fir_taps": {48000: 524288, 96000: 262144, 192000: 131072}},
}


def fir_limit(board, rate):
    table = BOARDS[board]["fir_taps"]
    best = min(table, key=lambda r: abs(r - rate))
    return int(table[best] * best / rate) if rate > best else table[best]


# DAC driver = device tree overlay(s) on the boot partition (aroio.txt). "auto": HATs
# with EEPROM (Raspberry Pi DAC+/DAC Pro/DigiAMP+, most HiFiBerry) announce themselves.
# Changing it needs a reboot. The image starts with no driver (= "auto", br2-external/board/rpi/aroio.txt).
DAC_DRIVERS = [
    {"id": "auto", "label": "Automatisch", "hint": "Die Aufsteckkarte meldet sich selbst (EEPROM).", "lines": []},
    {"id": "aroio", "label": "Aroio DAC", "hint": "Aroio SU, EX, LT",
     "lines": ["dtoverlay=hifiberry-dacplus", "dtoverlay=act-led,gpio=22",
               "dtparam=act_led_trigger=heartbeat"]},
    {"id": "rpi-dacplus", "label": "Raspberry Pi DAC+ / DAC Pro (IQaudio)", "hint": "", "lines": ["dtoverlay=iqaudio-dacplus"]},
    {"id": "rpi-digiamp", "label": "Raspberry Pi DigiAMP+ (IQaudio)", "hint": "Mit Verstärker",
     "lines": ["dtoverlay=iqaudio-dacplus,unmute_amp"]},
    {"id": "hifiberry-dacplus", "label": "HiFiBerry DAC+ / DAC2 Pro", "hint": "", "lines": ["dtoverlay=hifiberry-dacplus"]},
    {"id": "hifiberry-dac", "label": "HiFiBerry DAC / MiniAmp", "hint": "", "lines": ["dtoverlay=hifiberry-dac"]},
    {"id": "hifiberry-digi", "label": "HiFiBerry Digi+ (S/PDIF)", "hint": "Digitaler Ausgang", "lines": ["dtoverlay=hifiberry-digi"]},
    {"id": "allo-boss", "label": "Allo Boss DAC", "hint": "", "lines": ["dtoverlay=allo-boss-dac-pcm512x-audio"]},
    {"id": "onboard", "label": "Ohne Aufsteckkarte (HDMI, Kopfhörerbuchse)", "hint": "Kopfhörerbuchse nur Pi 3 und 4",
     "lines": ["dtparam=audio=on"]},
]
DAC_DRIVER_IDS = [d["id"] for d in DAC_DRIVERS]


def dac_driver_lines(driver_id):
    d = next((x for x in DAC_DRIVERS if x["id"] == driver_id), DAC_DRIVERS[0])
    return ["# written by aroiod: " + d["label"]] + d["lines"]


MODEL_IDS = list(MODELS)

# Aroio remote (RC5, aroio-ng /etc/lirc/lircd.conf: 13 bit codes 0x160C ...): rc-core
# scancode = address << 8 | command. Other remotes are taught in the app.
DEFAULT_IR_MAP = {
    "0x180d": "KEY_MUTE", "0x1811": "KEY_VOLUMEDOWN", "0x1810": "KEY_VOLUMEUP",
    "0x1835": "KEY_PLAYPAUSE", "0x1836": "KEY_STOP", "0x1832": "KEY_PREVIOUS", "0x1834": "KEY_NEXT",
}
IR_ACTIONS = ["KEY_PLAYPAUSE", "KEY_STOP", "KEY_NEXT", "KEY_PREVIOUS", "KEY_VOLUMEUP", "KEY_VOLUMEDOWN",
              "KEY_MUTE", "KEY_1", "KEY_2", "KEY_3", "KEY_4", "KEY_5"]


# KMS graphics: the HDMI info screen (framebuffer, display detection) and CEC. No HDMI
# audio (it would add sound cards). In aroio.txt, not config.txt: updates do not replace
# config.txt, aroiod keeps aroio.txt up to date (Device.sync_boot_config).
KMS_LINE = "dtoverlay=vc4-kms-v3d,noaudio"


def boot_lines(driver_id, model_id, ir=False):
    """Contents of aroio.txt on the boot partition: graphics, DAC driver and the model's
    controls (rotary encoder, key). Changes need a reboot. The info screen turns itself
    (hardware.display_rotate), so that needs no line here."""
    lines = dac_driver_lines(driver_id)
    lines.insert(1, KMS_LINE)
    model = MODELS.get(model_id) or {}
    enc = model.get("encoder")
    if enc:
        lines.append(f"dtoverlay=rotary-encoder,pin_a={enc['a']},pin_b={enc['b']},relative_axis=1")
    key = (model.get("buttons") or {}).get("play_pause")
    if key:
        lines.append(f'dtoverlay=gpio-key,gpio={key},keycode=164,label="PLAYPAUSE"')
    if ir:
        lines.append(f"dtoverlay=gpio-ir,gpio_pin={COMMON_PINS['ir']}")
    return lines
