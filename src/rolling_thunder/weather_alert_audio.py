"""Background-safe audible cues for location-aware weather alerts."""

from __future__ import annotations

import io
import math
import struct
import subprocess
import wave
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from rolling_thunder.weather_alert_notification_policy import (
    WeatherAlertAudioCue,
)

_SAMPLE_RATE = 16_000
_AMPLITUDE = 7_000
_TIMEOUT_S = 5.0
_MAX_ERROR_LENGTH = 500

TonePattern = tuple[tuple[float | None, float], ...]


class WeatherAlertAudioError(Exception):
    """Raised when a weather-alert cue cannot be played safely."""


class WeatherAlertAudioPlayer(Protocol):
    """Small playback boundary executed only from the alert worker."""

    def play(self, cue: WeatherAlertAudioCue) -> None:
        """Play one bounded, non-EAS weather-alert cue."""
        ...


@dataclass(frozen=True, slots=True)
class AudioCommandResult:
    """Minimal command outcome used by the testable ALSA adapter."""

    return_code: int
    stderr: str = ""


AudioCommandRunner = Callable[
    [tuple[str, ...], bytes, float],
    AudioCommandResult,
]


_PATTERNS: dict[WeatherAlertAudioCue, TonePattern] = {
    WeatherAlertAudioCue.URGENT: (
        (880.0, 0.16),
        (None, 0.08),
        (880.0, 0.16),
        (None, 0.08),
        (660.0, 0.22),
    ),
    WeatherAlertAudioCue.ATTENTION: (
        (660.0, 0.18),
        (None, 0.10),
        (880.0, 0.18),
    ),
    WeatherAlertAudioCue.WARNING: (
        (520.0, 0.20),
        (None, 0.12),
        (520.0, 0.20),
    ),
}


def _run_aplay(
    command: tuple[str, ...],
    payload: bytes,
    timeout_s: float,
) -> AudioCommandResult:
    try:
        completed = subprocess.run(
            command,
            input=payload,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout_s,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise WeatherAlertAudioError(
            f"Weather-alert audio command failed: {error}"
        ) from error

    stderr = completed.stderr.decode(
        "utf-8",
        errors="replace",
    ).strip()

    return AudioCommandResult(
        return_code=completed.returncode,
        stderr=stderr[:_MAX_ERROR_LENGTH],
    )


class AplayWeatherAlertAudioPlayer:
    """Play synthesized short cues through the Linux ALSA aplay command."""

    def __init__(
        self,
        *,
        audio_device: str = "default",
        runner: AudioCommandRunner = _run_aplay,
    ) -> None:
        device = audio_device.strip()

        if not device:
            raise ValueError(
                "Weather-alert audio device must not be blank."
            )

        self._audio_device = device
        self._runner = runner
        self._payloads = {
            cue: self._build_wav(pattern)
            for cue, pattern in _PATTERNS.items()
        }

    def play(self, cue: WeatherAlertAudioCue) -> None:
        """Play one audible cue; SILENT intentionally performs no work."""
        if cue is WeatherAlertAudioCue.SILENT:
            return

        payload = self._payloads.get(cue)

        if payload is None:
            raise WeatherAlertAudioError(
                f"Unsupported weather-alert audio cue: {cue.value}"
            )

        command = (
            "aplay",
            "-q",
            "-D",
            self._audio_device,
            "-t",
            "wav",
            "-",
        )

        result = self._runner(
            command,
            payload,
            _TIMEOUT_S,
        )

        if result.return_code == 0:
            return

        detail = (
            result.stderr
            or f"aplay exited with status {result.return_code}"
        )

        raise WeatherAlertAudioError(
            detail[:_MAX_ERROR_LENGTH]
        )

    @staticmethod
    def _build_wav(
        pattern: TonePattern,
    ) -> bytes:
        buffer = io.BytesIO()

        with wave.open(buffer, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(_SAMPLE_RATE)

            frames = bytearray()

            for frequency_hz, duration_s in pattern:
                sample_count = max(
                    1,
                    round(_SAMPLE_RATE * duration_s),
                )

                for sample_index in range(sample_count):
                    if frequency_hz is None:
                        sample = 0
                    else:
                        phase = (
                            2.0
                            * math.pi
                            * frequency_hz
                            * sample_index
                            / _SAMPLE_RATE
                        )
                        sample = round(
                            _AMPLITUDE * math.sin(phase)
                        )

                    frames.extend(
                        struct.pack("<h", sample)
                    )

            wav.writeframes(bytes(frames))

        return buffer.getvalue()
