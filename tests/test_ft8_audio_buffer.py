from __future__ import annotations

import pytest

from rolling_thunder.ft8.audio_buffer import (
    FT8AudioBuffer,
    FT8AudioBufferError,
)


def test_buffer_extracts_exact_ft8_period() -> None:
    buffer = FT8AudioBuffer()

    samples = bytes([1, 2]) * 180_000

    buffer.append(samples)

    result = buffer.extract(
        start_sample=0,
        sample_count=180_000,
    )

    assert result == samples


def test_buffer_discards_oldest_audio_when_full() -> None:
    buffer = FT8AudioBuffer(max_seconds=1)

    first = bytes([1, 2]) * 12_000
    second = bytes([3, 4]) * 12_000

    buffer.append(first)
    buffer.append(second)

    result = buffer.extract(
        start_sample=0,
        sample_count=12_000,
    )

    assert result == second


def test_buffer_tolerates_initial_missing_audio() -> None:
    buffer = FT8AudioBuffer()

    delayed_audio = bytes([5, 6]) * (12_000 * 2)

    buffer.append(delayed_audio)

    assert buffer.available_samples == 24_000


def test_buffer_rejects_bad_sample_alignment() -> None:
    buffer = FT8AudioBuffer()

    with pytest.raises(FT8AudioBufferError):
        buffer.append(b"\x00")


def test_buffer_rejects_unavailable_extract() -> None:
    buffer = FT8AudioBuffer()

    buffer.append(bytes([1, 2]) * 100)

    with pytest.raises(FT8AudioBufferError):
        buffer.extract(
            start_sample=0,
            sample_count=200,
        )
