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
