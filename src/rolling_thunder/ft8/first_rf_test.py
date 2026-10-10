"""Single supervised 2-second RF audio/PTT test; NEVER normal FT8 transmit."""

from __future__ import annotations

import argparse
import math
import struct
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import yaml

from rolling_thunder.ft8.encoder import FT8EncodedMessage, FT8Waveform
from rolling_thunder.ft8.hardware_transmit import (
    BoundedFT8HardwareTransmitExecutor,
    FT8HardwareTestAuthorization,
    FT8HardwareTestRequest,
)
from rolling_thunder.ft8.power_advisor import FT8PowerPolicy
from rolling_thunder.ft891_radio import Ft891Radio
from rolling_thunder.pyserial_cat_transport import PySerialCatTransport

_FREQUENCY_HZ = 14_074_000
_SAMPLE_RATE = 12_000
_SECONDS = 2


class TwoSecondLeftOnlyAudio:
    """Finite left-channel 1500-Hz signal; never a full FT8 message."""

    def __init__(self, device: str) -> None:
        if not device:
            raise ValueError("Missing explicit FT8 transmit audio device")
        self.device = device

    def play(self, waveform: FT8Waveform) -> None:
        # Conservative drive to limit ALC, hard stop on aplay timeout.
        pcm = bytearray()
        for index in range(_SAMPLE_RATE * _SECONDS):
            amplitude = int(1600 * math.sin(2 * math.pi * 1500 * index / _SAMPLE_RATE))
            pcm += struct.pack("<hh", amplitude, 0)
        subprocess.run(
            [
                "aplay",
                "-q",
                "-D",
                self.device,
                "-f",
                "S16_LE",
                "-c",
                "2",
                "-r",
                str(_SAMPLE_RATE),
                "-t",
                "raw",
                "-",
            ],
            input=bytes(pcm),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=True,
            timeout=2.8,
        )


def run(config_path: Path, *, authorization: str) -> None:
    if authorization != "I-AM-PARKED-DUMMY-LOAD-5W-ONE-TEST":
        raise ValueError("Explicit operator test token required")
    if (
        subprocess.run(
            ["systemctl", "is-active", "--quiet", "rolling-thunder.service"], check=False
        ).returncode
        == 0
    ):
        raise RuntimeError("Refusing while production service is active")
    cfg = yaml.safe_load(config_path.read_text())
    assert cfg["ft8"]["enabled"] is True
    assert cfg["ft8"]["transmit"]["enabled"] is False
    hardware = cfg["hardware"]
    device = hardware["radio_device"]
    audio_device = cfg["ft8"]["transmit"].get("audio_device")
    if not device or not audio_device:
        raise RuntimeError("CAT and audio devices must be explicitly configured")
    radio = Ft891Radio(
        PySerialCatTransport(
            Path(device),
            baud_rate=hardware.get("radio_baud_rate", 38400),
            timeout_s=hardware.get("radio_timeout_s", 1.0),
        )
    )
    radio.connect()
    try:
        if radio.read_power_watts() != 5:
            raise RuntimeError("Live CAT power not exactly 5W: NO PTT")
        executor = BoundedFT8HardwareTransmitExecutor(
            radio,
            TwoSecondLeftOnlyAudio(str(audio_device)),
            power_policy=FT8PowerPolicy(**cfg["ft8"].get("power", {})),
        )
        try:
            waveform = FT8Waveform(
                encoded=FT8EncodedMessage(
                    message="NO FT8 MESSAGE", packed_payload=b"0123456789", tones=(0,) * 79
                ),
                base_frequency_hz=1500,
                sample_rate_hz=_SAMPLE_RATE,
                pcm_s16le=b"\x00\x00",
            )
            print("RF TEST: one 2-second 1500-Hz audio burst; visually monitor TX/RX", flush=True)
            executor.execute_test(
                FT8HardwareTestRequest(
                    authorization=FT8HardwareTestAuthorization(
                        authorization_id="supervised-2s-dummyload",
                        approved_at_utc=datetime.now(UTC),
                    ),
                    waveform=waveform,
                    maximum_key_down_s=3.0,
                    expected_radio_frequency_hz=_FREQUENCY_HZ,
                    expected_radio_mode="USB",
                )
            )
            print("CAT TX0 returned; VERIFY RADIO PHYSICALLY IN RECEIVE", flush=True)
        finally:
            executor.close()
    finally:
        radio.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--authorization", required=True)
    args = parser.parse_args()
    run(args.config, authorization=args.authorization)


if __name__ == "__main__":
    main()
