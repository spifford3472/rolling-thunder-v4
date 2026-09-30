"""Checkpoint 6 FT8 playback boundary and ALSA adapter.

This module can write already-prepared FT8 PCM to one explicit ALSA playback
device. It has no CAT, PTT, QSO-state, retry, UI, voice, network, or RF
authority.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Protocol

from rolling_thunder.ft8.encoder import (
    FT8_PCM_SAMPLE_WIDTH_BYTES,
    FT8_SAMPLE_RATE_HZ,
    FT8_SLOT_SAMPLES,
    FT8Waveform,
)


class FT8AudioOutputError(RuntimeError):
    """Bounded FT8 playback failure."""


class FT8AudioOutput(Protocol):
    """Project-owned finite PCM playback boundary."""

    def play(self, waveform: FT8Waveform) -> None:
        """Play exactly one already-prepared FT8 slot waveform."""
        ...


@dataclass(frozen=True, slots=True)
class AlsaPlaybackCommand:
    """Immutable finite aplay command description."""

    device: str
    sample_rate_hz: int = FT8_SAMPLE_RATE_HZ

    def __post_init__(self) -> None:
        if not self.device.strip():
            raise ValueError("FT8 playback device must not be blank")
        if self.sample_rate_hz != FT8_SAMPLE_RATE_HZ:
            raise ValueError("FT8 playback must use 12000 Hz")

    def argv(self) -> tuple[str, ...]:
        return (
            "aplay",
            "-q",
            "-D",
            self.device,
            "-f",
            "S16_LE",
            "-c",
            "2",
            "-r",
            str(self.sample_rate_hz),
            "-t",
            "raw",
            "-",
        )


class AlsaAplayFT8AudioOutput:
    """Finite ALSA playback adapter for one immutable FT8 waveform."""

    def __init__(self, device: str, *, timeout_s: float = 20.0) -> None:
        if timeout_s <= 0:
            raise ValueError("FT8 playback timeout must be positive")
        self._command = AlsaPlaybackCommand(device)
        self._timeout_s = timeout_s

    @property
    def device(self) -> str:
        return self._command.device

    def play(self, waveform: FT8Waveform) -> None:
        if waveform.sample_rate_hz != FT8_SAMPLE_RATE_HZ:
            raise ValueError("FT8 playback waveform must use 12000 Hz")
        expected_bytes = FT8_SLOT_SAMPLES * FT8_PCM_SAMPLE_WIDTH_BYTES
        if len(waveform.pcm_s16le) != expected_bytes:
            raise ValueError(
                f"FT8 playback waveform must contain exactly {expected_bytes} PCM bytes"
            )

        stereo_pcm = self._left_only_stereo(waveform.pcm_s16le)

        try:
            completed = subprocess.run(
                self._command.argv(),
                input=stereo_pcm,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                check=False,
                timeout=self._timeout_s,
            )
        except OSError as exc:
            raise FT8AudioOutputError(f"could not start FT8 playback: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise FT8AudioOutputError("FT8 playback timed out") from exc

        if completed.returncode != 0:
            detail = completed.stderr.decode(errors="replace").strip()
            suffix = f": {detail}" if detail else ""
            raise FT8AudioOutputError(
                f"FT8 playback exited {completed.returncode}{suffix}"
            )


    @staticmethod
    def _left_only_stereo(mono_pcm_s16le: bytes) -> bytes:
        """Expand mono S16_LE to stereo with payload left and silence right."""
        stereo = bytearray(len(mono_pcm_s16le) * 2)
        target = memoryview(stereo)
        source = memoryview(mono_pcm_s16le)
        for offset in range(0, len(mono_pcm_s16le), 2):
            target[offset * 2 : offset * 2 + 2] = source[offset : offset + 2]
        return bytes(stereo)
