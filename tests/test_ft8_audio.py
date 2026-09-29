"""Tests for the receive-only FT8 audio boundary."""

from io import BytesIO
from typing import Any, cast

import pytest

from rolling_thunder.ft8.audio import (
    FT8_PERIOD_BYTES,
    FT8_SAMPLE_RATE_HZ,
    FT8AudioInputError,
    AlsaArecordFT8AudioInput,
    AlsaCaptureCommand,
)


def test_alsa_capture_command_is_receive_only_12khz_mono_s16le() -> None:
    command = AlsaCaptureCommand("plughw:CARD=Device,DEV=0")

    assert command.argv() == (
        "arecord",
        "-q",
        "-D",
        "plughw:CARD=Device,DEV=0",
        "-f",
        "S16_LE",
        "-c",
        "1",
        "-r",
        "12000",
        "-t",
        "raw",
        "-",
    )
    assert FT8_SAMPLE_RATE_HZ == 12_000
    assert FT8_PERIOD_BYTES == 360_000
    assert all(token not in command.argv() for token in ("aplay", "ptt", "cat", "mox"))


def test_alsa_audio_input_rejects_blank_device() -> None:
    try:
        AlsaArecordFT8AudioInput("   ")
    except ValueError as exc:
        assert "must not be blank" in str(exc)
    else:
        raise AssertionError("blank FT8 audio device was accepted")


class _ShortProcess:
    def __init__(self) -> None:
        self.stdout = BytesIO(b"\x00\x00" * 100)
        self.stderr = BytesIO(b"capture ended")


def test_incomplete_capture_is_rejected() -> None:
    audio = AlsaArecordFT8AudioInput("plughw:CARD=Device,DEV=0")
    process = cast(Any, _ShortProcess())

    with pytest.raises(FT8AudioInputError, match="before a complete period"):
        audio._read_exact(process, FT8_PERIOD_BYTES)
