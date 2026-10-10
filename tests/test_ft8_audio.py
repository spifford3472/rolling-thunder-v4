"""Tests for the receive-only FT8 audio boundary."""

from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Any, cast

import pytest

from rolling_thunder.ft8.audio import (
    FT8_PERIOD_BYTES,
    FT8_SAMPLE_RATE_HZ,
    AlsaArecordFT8AudioInput,
    AlsaCaptureCommand,
    FT8AudioInputError,
)
from rolling_thunder.ft8.domain import FT8Period
from rolling_thunder.ft8.timing import FakeFT8Clock


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



class _LiveProcess:
    def poll(self) -> None:
        return None


class _ReanchorBuffer:
    def __init__(self, *, next_sample: int, pcm: bytes, first_sample: int = 0) -> None:
        self.first_sample = first_sample
        self.next_sample = next_sample
        self._pcm = pcm

    def extract(self, *, start_sample: int, sample_count: int) -> bytes:
        assert sample_count == 180_000
        return self._pcm


def test_audio_input_reanchors_next_period_to_current_utc_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completed = FT8Period.from_utc(
        datetime(2026, 10, 4, 0, 0, 0, tzinfo=UTC)
    )
    clock = FakeFT8Clock(completed.start_utc + timedelta(seconds=15))
    audio = AlsaArecordFT8AudioInput(
        "plughw:CARD=Device,DEV=0",
        clock=clock,
    )

    period_start_sample = 1_000_000
    nominal_end_sample = period_start_sample + 180_000
    boundary_sample = nominal_end_sample + 600
    pcm = b"\x00\x00" * 180_000
    buffer = _ReanchorBuffer(next_sample=boundary_sample, pcm=pcm)

    audio._process = cast(Any, _LiveProcess())
    audio._buffer = cast(Any, buffer)
    audio._next_period = completed
    audio._next_period_start_sample = period_start_sample

    monkeypatch.setattr(
        audio,
        "_wait_for_samples",
        lambda process, target_buffer, end_sample: None,
    )

    result = audio.read_period()

    assert result.period == completed
    assert audio._next_period == FT8Period(completed.index + 1)
    assert audio._next_period_start_sample == boundary_sample
    assert audio._next_period_start_sample != nominal_end_sample


def test_utc_reanchor_prevents_90_day_usb_sample_drift_accumulation() -> None:
    start = datetime(2026, 10, 4, 0, 0, 0, tzinfo=UTC)
    first_period = FT8Period.from_utc(start)
    runtime_seconds = 90 * 24 * 60 * 60
    period_count = runtime_seconds // 15

    completed = FT8Period(first_period.index + period_count - 1)
    clock = FakeFT8Clock(completed.start_utc + timedelta(seconds=15))
    audio = AlsaArecordFT8AudioInput(
        "plughw:CARD=Device,DEV=0",
        clock=clock,
    )

    # 100 ppm is intentionally conservative and demonstrates why a USB audio
    # oscillator cannot be treated as a UTC clock over multi-month uptime.
    drift_ppm = 100
    nominal_samples = runtime_seconds * FT8_SAMPLE_RATE_HZ
    boundary_sample = round(
        nominal_samples * (1 + drift_ppm / 1_000_000)
    )
    buffer = _ReanchorBuffer(
        next_sample=boundary_sample,
        pcm=b"\x00\x00" * 180_000,
    )

    next_period, next_start_sample, lateness_ms = audio._realign_next_period(
        cast(Any, buffer),
        completed_period=completed,
    )

    accumulated_error_samples = boundary_sample - nominal_samples

    assert accumulated_error_samples > 180_000
    assert next_period == FT8Period(completed.index + 1)
    assert next_start_sample == boundary_sample
    assert lateness_ms == 0.0


def test_audio_boundary_back_projects_scheduler_wake_lateness() -> None:
    period = FT8Period.from_utc(datetime(2026, 10, 4, 0, 0, 0, tzinfo=UTC))
    clock = FakeFT8Clock(period.start_utc + timedelta(milliseconds=50))
    audio = AlsaArecordFT8AudioInput(
        "plughw:CARD=Device,DEV=0",
        clock=clock,
    )
    buffer = _ReanchorBuffer(
        next_sample=1_000_600,
        first_sample=900_000,
        pcm=b"\x00\x00" * 180_000,
    )

    aligned_period, boundary_sample, lateness_ms = audio._align_boundary(
        cast(Any, buffer),
        period,
    )

    assert aligned_period == period
    assert boundary_sample == 1_000_000
    assert lateness_ms == pytest.approx(50.0)
