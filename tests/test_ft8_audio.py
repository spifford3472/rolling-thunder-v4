"""Tests for the receive-only FT8 audio boundary."""

from rolling_thunder.ft8.audio import (
    FT8_PERIOD_BYTES,
    FT8_SAMPLE_RATE_HZ,
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
