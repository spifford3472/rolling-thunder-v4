"""Offline speech-recognition adapters for phonetic callsign capture."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Final, Protocol


CALLSIGN_GRAMMAR: Final[tuple[str, ...]] = (
    "alfa",
    "alpha",
    "bravo",
    "charlie",
    "delta",
    "echo",
    "foxtrot",
    "golf",
    "hotel",
    "india",
    "italy",
    "juliet",
    "kilo",
    "lima",
    "mike",
    "november",
    "oscar",
    "papa",
    "quebec",
    "queen",
    "romeo",
    "sierra",
    "sugar",
    "tango",
    "uniform",
    "victor",
    "victoria",
    "whiskey",
    "x ray",
    "yankee",
    "zulu",
    "zanzibar",
    "zero",
    "oh",
    "one",
    "two",
    "three",
    "tree",
    "four",
    "five",
    "fife",
    "six",
    "seven",
    "eight",
    "nine",
    "niner",
    "slash",
    "stroke",
    "portable",
    "mobile",
    "[unk]",
)


class SpeechRecognitionError(RuntimeError):
    """Raised when microphone capture or offline recognition cannot complete."""


class SpeechRecognizer(Protocol):
    """Return one finalized sequence of recognized callsign words."""

    def capture_tokens(self) -> tuple[str, ...]:
        """Capture one push-to-listen utterance and return normalized tokens."""


class VoskCallsignRecognizer:
    """Capture bounded ALSA audio and recognize it with a constrained Vosk grammar."""

    def __init__(
        self,
        *,
        model_path: Path,
        audio_device: str,
        duration_s: int = 8,
        sample_rate: int = 16_000,
    ) -> None:
        if duration_s < 1:
            raise ValueError("Speech capture duration must be at least one second.")
        if sample_rate < 8_000:
            raise ValueError("Speech sample rate must be at least 8000 Hz.")
        if not audio_device.strip():
            raise ValueError("Speech audio device must not be empty.")

        self._model_path = model_path
        self._audio_device = audio_device
        self._duration_s = duration_s
        self._sample_rate = sample_rate

    def capture_tokens(self) -> tuple[str, ...]:
        """Record one bounded utterance and return finalized uppercase words."""
        if not self._model_path.is_dir():
            raise SpeechRecognitionError(
                f"Vosk model directory was not found: {self._model_path}"
            )

        command = (
            "arecord",
            "--quiet",
            f"--device={self._audio_device}",
            "--file-type=raw",
            "--format=S16_LE",
            f"--rate={self._sample_rate}",
            "--channels=1",
            f"--duration={self._duration_s}",
        )
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                timeout=self._duration_s + 3,
            )
        except FileNotFoundError as error:
            raise SpeechRecognitionError(
                "ALSA arecord was not found; install the alsa-utils package."
            ) from error
        except subprocess.TimeoutExpired as error:
            raise SpeechRecognitionError("Microphone capture timed out.") from error

        if completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", errors="replace").strip()
            message = detail or f"arecord exited with status {completed.returncode}"
            raise SpeechRecognitionError(f"Microphone capture failed: {message}")
        if not completed.stdout:
            raise SpeechRecognitionError("Microphone capture returned no audio.")

        try:
            from vosk import KaldiRecognizer, Model, SetLogLevel
        except ImportError as error:
            raise SpeechRecognitionError(
                "Vosk is not installed; install the Rolling Thunder speech dependency."
            ) from error

        SetLogLevel(-1)
        try:
            model = Model(str(self._model_path))
            recognizer = KaldiRecognizer(
                model,
                self._sample_rate,
                json.dumps(CALLSIGN_GRAMMAR),
            )
            for offset in range(0, len(completed.stdout), 8_000):
                recognizer.AcceptWaveform(completed.stdout[offset : offset + 8_000])
            result = json.loads(recognizer.FinalResult())
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
            raise SpeechRecognitionError(f"Vosk recognition failed: {error}") from error

        text = str(result.get("text", "")).strip()
        if not text:
            return ()
        return tuple(token.upper() for token in text.split())
