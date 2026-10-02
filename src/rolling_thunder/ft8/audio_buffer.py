"""Rolling PCM buffer primitives for FT8 receive timing recovery."""

from __future__ import annotations

import threading
from collections import deque
from time import monotonic

FT8_SAMPLE_RATE_HZ = 12_000
FT8_SAMPLE_WIDTH_BYTES = 2


class FT8AudioBufferError(RuntimeError):
    """Safe FT8 audio buffer failure."""


class FT8AudioBuffer:
    """Thread-safe fixed-size rolling signed 16-bit PCM sample buffer.

    Sample positions are absolute from construction of the buffer. This lets a
    continuous capture producer keep writing while a consumer remembers an
    exact sample boundary and later extracts that range after it arrives.
    """

    def __init__(
        self,
        *,
        max_seconds: float = 30.0,
        sample_rate_hz: int = FT8_SAMPLE_RATE_HZ,
        sample_width_bytes: int = FT8_SAMPLE_WIDTH_BYTES,
    ) -> None:
        if max_seconds <= 0:
            raise ValueError("max_seconds must be positive")
        if sample_rate_hz <= 0:
            raise ValueError("sample_rate_hz must be positive")
        if sample_width_bytes <= 0:
            raise ValueError("sample_width_bytes must be positive")

        self._sample_width_bytes = sample_width_bytes
        self._max_samples = int(max_seconds * sample_rate_hz)
        self._chunks: deque[bytes] = deque()
        self._retained_samples = 0
        self._first_sample = 0
        self._next_sample = 0
        self._condition = threading.Condition()

    @property
    def available_samples(self) -> int:
        """Number of PCM samples currently retained."""
        with self._condition:
            return self._retained_samples

    @property
    def first_sample(self) -> int:
        """Absolute index of the oldest retained sample."""
        with self._condition:
            return self._first_sample

    @property
    def next_sample(self) -> int:
        """Absolute index immediately after the newest captured sample."""
        with self._condition:
            return self._next_sample

    def append(self, pcm_s16le: bytes) -> None:
        """Append PCM samples and discard oldest chunks when full."""
        if len(pcm_s16le) % self._sample_width_bytes != 0:
            raise FT8AudioBufferError("PCM byte length must align to sample width")

        if not pcm_s16le:
            return

        sample_count = len(pcm_s16le) // self._sample_width_bytes

        with self._condition:
            self._chunks.append(pcm_s16le)
            self._retained_samples += sample_count
            self._next_sample += sample_count

            while self._retained_samples > self._max_samples:
                oldest = self._chunks.popleft()
                discarded = len(oldest) // self._sample_width_bytes
                self._retained_samples -= discarded
                self._first_sample += discarded

            self._condition.notify_all()

    def wait_for_sample(
        self,
        end_sample: int,
        *,
        timeout_s: float,
    ) -> bool:
        """Wait until the absolute end-sample position has been captured."""
        if end_sample < 0:
            raise ValueError("end_sample must not be negative")
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")

        deadline = monotonic() + timeout_s

        with self._condition:
            while self._next_sample < end_sample:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
            return True

    def extract(
        self,
        *,
        start_sample: int,
        sample_count: int,
    ) -> bytes:
        """Extract an exact absolute sample range from retained PCM."""
        if start_sample < 0:
            raise FT8AudioBufferError("start_sample must not be negative")
        if sample_count <= 0:
            raise FT8AudioBufferError("sample_count must be positive")

        end_sample = start_sample + sample_count

        with self._condition:
            if start_sample < self._first_sample:
                raise FT8AudioBufferError(
                    "requested samples have rolled out of the buffer"
                )

            if end_sample > self._next_sample:
                raise FT8AudioBufferError("requested samples are not available")

            all_pcm = b"".join(self._chunks)
            relative_start = start_sample - self._first_sample

            start_byte = relative_start * self._sample_width_bytes
            end_byte = (
                relative_start + sample_count
            ) * self._sample_width_bytes

            return all_pcm[start_byte:end_byte]
