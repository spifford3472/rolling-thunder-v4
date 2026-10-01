"""Rolling PCM buffer primitives for FT8 receive timing recovery."""

from __future__ import annotations

from collections import deque

FT8_SAMPLE_RATE_HZ = 12_000
FT8_SAMPLE_WIDTH_BYTES = 2


class FT8AudioBufferError(RuntimeError):
    """Safe FT8 audio buffer failure."""


class FT8AudioBuffer:
    """Fixed-size rolling signed 16-bit PCM sample buffer.

    This class intentionally knows nothing about:
    - ALSA
    - radios
    - FT8 decoding
    - UTC timing

    It only stores and returns PCM samples.
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
        self._samples: deque[bytes] = deque()
        self._sample_count = 0

    @property
    def available_samples(self) -> int:
        """Number of PCM samples currently stored."""
        return self._sample_count

    def append(self, pcm_s16le: bytes) -> None:
        """Append PCM samples and discard oldest samples when full."""
        if len(pcm_s16le) % self._sample_width_bytes != 0:
            raise FT8AudioBufferError(
                "PCM byte length must align to sample width"
            )

        if not pcm_s16le:
            return

        self._samples.append(pcm_s16le)
        self._sample_count += len(pcm_s16le) // self._sample_width_bytes

        while self._sample_count > self._max_samples:
            oldest = self._samples.popleft()
            self._sample_count -= len(oldest) // self._sample_width_bytes

    def extract(
        self,
        *,
        start_sample: int,
        sample_count: int,
    ) -> bytes:
        """Extract an exact sample range from the rolling buffer."""
        if start_sample < 0:
            raise FT8AudioBufferError("start_sample must not be negative")

        if sample_count <= 0:
            raise FT8AudioBufferError("sample_count must be positive")

        if start_sample + sample_count > self._sample_count:
            raise FT8AudioBufferError(
                "requested samples are not available"
            )

        all_pcm = b"".join(self._samples)

        start_byte = start_sample * self._sample_width_bytes
        end_byte = (
            start_sample + sample_count
        ) * self._sample_width_bytes

        return all_pcm[start_byte:end_byte]
