from __future__ import annotations

import threading
import time

import pytest

from rolling_thunder.ft8.audio_buffer import (
    FT8AudioBuffer,
    FT8AudioBufferError,
)


def test_buffer_extracts_exact_ft8_period() -> None:
    buffer = FT8AudioBuffer()
    samples = bytes([1, 2]) * 180_000

    buffer.append(samples)

    assert buffer.extract(start_sample=0, sample_count=180_000) == samples


def test_buffer_tracks_absolute_sample_positions() -> None:
    buffer = FT8AudioBuffer(max_seconds=1)

    first = bytes([1, 2]) * 12_000
    second = bytes([3, 4]) * 12_000

    buffer.append(first)

    assert buffer.first_sample == 0
    assert buffer.next_sample == 12_000

    buffer.append(second)

    assert buffer.first_sample == 12_000
    assert buffer.next_sample == 24_000
    assert buffer.available_samples == 12_000
    assert buffer.extract(
        start_sample=12_000,
        sample_count=12_000,
    ) == second


def test_buffer_waits_for_future_absolute_sample() -> None:
    buffer = FT8AudioBuffer()

    def writer() -> None:
        time.sleep(0.02)
        buffer.append(bytes([5, 6]) * 100)

    thread = threading.Thread(target=writer)
    thread.start()

    try:
        assert buffer.wait_for_sample(100, timeout_s=0.5)
    finally:
        thread.join(timeout=1)


@pytest.mark.parametrize("delay_samples", [6_000, 12_000, 24_000])
def test_buffer_preserves_period_after_startup_delay(
    delay_samples: int,
) -> None:
    buffer = FT8AudioBuffer()

    startup_audio = bytes([1, 2]) * delay_samples
    period_audio = bytes([3, 4]) * 180_000

    buffer.append(startup_audio)
    period_start = buffer.next_sample
    buffer.append(period_audio)

    assert buffer.extract(
        start_sample=period_start,
        sample_count=180_000,
    ) == period_audio


def test_buffer_rejects_bad_sample_alignment() -> None:
    buffer = FT8AudioBuffer()

    with pytest.raises(FT8AudioBufferError):
        buffer.append(b"\x00")


def test_buffer_rejects_unavailable_extract() -> None:
    buffer = FT8AudioBuffer()
    buffer.append(bytes([1, 2]) * 100)

    with pytest.raises(FT8AudioBufferError):
        buffer.extract(start_sample=0, sample_count=200)


def test_buffer_rejects_samples_that_have_rolled_out() -> None:
    buffer = FT8AudioBuffer(max_seconds=1)

    buffer.append(bytes([1, 2]) * 12_000)
    buffer.append(bytes([3, 4]) * 12_000)

    with pytest.raises(FT8AudioBufferError, match="rolled out"):
        buffer.extract(start_sample=0, sample_count=100)
