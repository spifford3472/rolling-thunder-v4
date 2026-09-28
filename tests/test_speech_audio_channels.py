"""Tests for deterministic speech capture channel conversion."""

import struct

import pytest

from rolling_thunder.speech_recognition import (
    SpeechRecognitionError,
    _downmix_s16le_to_mono,
)


def test_mono_audio_is_preserved() -> None:
    audio = struct.pack("<3h", -1000, 0, 1000)

    assert _downmix_s16le_to_mono(audio, 1) == audio


def test_stereo_audio_is_averaged_to_mono() -> None:
    stereo = struct.pack(
        "<6h",
        1000,
        -1000,
        3000,
        1000,
        -2000,
        -1000,
    )

    mono = _downmix_s16le_to_mono(stereo, 2)

    assert struct.unpack("<3h", mono) == (0, 2000, -1500)


def test_three_channel_audio_is_averaged_to_mono() -> None:
    multichannel = struct.pack(
        "<6h",
        300,
        600,
        900,
        -300,
        -600,
        -900,
    )

    mono = _downmix_s16le_to_mono(multichannel, 3)

    assert struct.unpack("<2h", mono) == (600, -600)


def test_incomplete_multichannel_frame_is_rejected() -> None:
    with pytest.raises(
        SpeechRecognitionError,
        match="incomplete multichannel audio frame",
    ):
        _downmix_s16le_to_mono(b"\x00\x01\x02", 2)


def test_invalid_channel_count_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="channels must be at least one",
    ):
        _downmix_s16le_to_mono(b"", 0)
