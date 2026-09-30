"""Tests for the Checkpoint 6 finite FT8 playback boundary."""

from __future__ import annotations

import subprocess
from typing import Any

import pytest

from rolling_thunder.ft8.audio_output import (
    AlsaAplayFT8AudioOutput,
    AlsaPlaybackCommand,
    FT8AudioOutputError,
)
from rolling_thunder.ft8.encoder import (
    FT8_SAMPLE_RATE_HZ,
    FT8_SLOT_SAMPLES,
    FT8EncodedMessage,
    FT8Waveform,
)


def _waveform(*, sample_rate_hz: int = FT8_SAMPLE_RATE_HZ) -> FT8Waveform:
    return FT8Waveform(
        encoded=FT8EncodedMessage(
            message="K1ABC KI5VNB EM79",
            packed_payload=b"0123456789",
            tones=tuple(0 for _ in range(79)),
        ),
        base_frequency_hz=1500,
        sample_rate_hz=sample_rate_hz,
        pcm_s16le=b"\x00\x00" * FT8_SLOT_SAMPLES,
    )


def test_alsa_playback_command_is_finite_12khz_mono_s16le() -> None:
    command = AlsaPlaybackCommand("plughw:CARD=Device,DEV=0")

    assert command.argv() == (
        "aplay",
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
    assert all(token not in command.argv() for token in ("cat", "ptt", "mox", "ttyUSB"))


def test_playback_rejects_blank_device() -> None:
    with pytest.raises(ValueError, match="must not be blank"):
        AlsaAplayFT8AudioOutput("   ")


def test_playback_rejects_wrong_sample_rate() -> None:
    output = AlsaAplayFT8AudioOutput("plughw:CARD=Device,DEV=0")

    with pytest.raises(ValueError, match="12000 Hz"):
        output.play(_waveform(sample_rate_hz=8000))


def test_playback_rejects_wrong_pcm_length() -> None:
    waveform = _waveform()
    truncated = FT8Waveform(
        encoded=waveform.encoded,
        base_frequency_hz=waveform.base_frequency_hz,
        sample_rate_hz=waveform.sample_rate_hz,
        pcm_s16le=waveform.pcm_s16le[:-2],
    )
    output = AlsaAplayFT8AudioOutput("plughw:CARD=Device,DEV=0")

    with pytest.raises(ValueError, match="exactly 360000 PCM bytes"):
        output.play(truncated)


def test_playback_passes_exact_pcm_to_finite_aplay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waveform = _waveform()
    calls: list[dict[str, Any]] = []

    def fake_run(argv: tuple[str, ...], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append({"argv": argv, **kwargs})
        return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    output = AlsaAplayFT8AudioOutput("plughw:CARD=Device,DEV=0")

    output.play(waveform)

    assert len(calls) == 1
    assert calls[0]["input"] == waveform.pcm_s16le
    assert calls[0]["timeout"] == 20.0
    assert calls[0]["check"] is False


def test_playback_wraps_aplay_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(
        argv: tuple[str, ...], **kwargs: Any
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(argv, 1, stdout=b"", stderr=b"device busy")

    monkeypatch.setattr(subprocess, "run", fake_run)
    output = AlsaAplayFT8AudioOutput("plughw:CARD=Device,DEV=0")

    with pytest.raises(FT8AudioOutputError, match="device busy"):
        output.play(_waveform())


def test_playback_wraps_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(argv: tuple[str, ...], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.TimeoutExpired(argv, 20)

    monkeypatch.setattr(subprocess, "run", fake_run)
    output = AlsaAplayFT8AudioOutput("plughw:CARD=Device,DEV=0")

    with pytest.raises(FT8AudioOutputError, match="timed out"):
        output.play(_waveform())
