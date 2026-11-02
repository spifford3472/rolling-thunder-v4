"""Offline speech-recognition adapters and shared lazy Vosk model loading."""

from __future__ import annotations

import importlib
import json
import sys
from array import array
from pathlib import Path
from threading import Event, Lock
from typing import Any, Final, Protocol, cast

from rolling_thunder.audio_capture import AudioCaptureCancelled, AudioCaptureError, capture_alsa_pcm

CALLSIGN_GRAMMAR: Final[tuple[str, ...]] = (
    "alfa", "alpha", "bravo", "charlie", "delta", "echo", "foxtrot",
    "golf", "hotel", "india", "italy", "juliet", "kilo", "lima",
    "mike", "november", "oscar", "papa", "quebec", "queen", "romeo",
    "sierra", "sugar", "tango", "uniform", "victor", "victoria",
    "whiskey", "x ray", "yankee", "zulu", "zanzibar", "zero", "oh",
    "one", "two", "three", "tree", "four", "five", "fife", "six",
    "seven", "eight", "nine", "niner", "slash", "stroke", "portable",
    "mobile", "[unk]",
)


class SpeechRecognitionError(RuntimeError):
    """Raised when microphone capture or offline recognition cannot complete."""


class SpeechRecognitionCancelled(SpeechRecognitionError):
    """Raised when an operator priority request cancels callsign capture."""


class VoskRecognizer(Protocol):
    """Small typed Vosk recognizer surface shared by speech features."""

    def AcceptWaveform(self, audio: bytes) -> bool: ...
    def FinalResult(self) -> str: ...


class SpeechRecognizer(Protocol):
    """Return one finalized sequence of recognized callsign words."""

    def capture_tokens(self, stop_event: Event | None = None) -> tuple[str, ...]:
        """Capture one bounded push-to-listen utterance and normalize its words."""


class VoskModelProvider:
    """Load one offline Vosk model lazily and reuse it across serialized sessions.

    Call ``create_recognizer`` from a background capture/recognition worker. The
    provider constructor performs no import, filesystem access, or model loading.
    """

    def __init__(self, model_path: Path) -> None:
        self._model_path = model_path
        self._lock = Lock()
        self._vosk: Any = None
        self._model: Any = None

    def warm(self, sample_rate: int = 16_000) -> None:
        """Load the model in a background preparation worker without audio I/O."""
        self.create_recognizer(sample_rate, ("tron status", "[unk]"))

    def create_recognizer(
        self, sample_rate: int, grammar: tuple[str, ...]
    ) -> VoskRecognizer:
        """Return a new recognizer sharing the one lazily loaded model."""
        with self._lock:
            if self._model is None:
                if not self._model_path.is_dir():
                    raise SpeechRecognitionError(
                        f"Vosk model directory was not found: {self._model_path}"
                    )
                try:
                    vosk = cast(Any, importlib.import_module("vosk"))
                except ImportError as error:
                    raise SpeechRecognitionError(
                        "Vosk is not installed; install the Rolling Thunder speech dependency."
                    ) from error
                try:
                    vosk.SetLogLevel(-1)
                    self._model = vosk.Model(str(self._model_path))
                    self._vosk = vosk
                except (OSError, RuntimeError, ValueError) as error:
                    self._model = None
                    self._vosk = None
                    raise SpeechRecognitionError(f"Vosk model could not be loaded: {error}") from error
            vosk_module = self._vosk
            model = self._model
        if vosk_module is None or model is None:
            raise SpeechRecognitionError("Vosk model is unavailable")
        try:
            factory = vosk_module.KaldiRecognizer
            return cast(VoskRecognizer, factory(model, sample_rate, json.dumps(grammar)))
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            raise SpeechRecognitionError(f"Vosk recognizer could not be created: {error}") from error


def _downmix_s16le_to_mono(audio: bytes, channels: int) -> bytes:
    """Return mono S16_LE audio from interleaved input channels."""
    if channels < 1:
        raise ValueError("Speech capture channels must be at least one.")
    frame_size = channels * 2
    if len(audio) % frame_size != 0:
        raise SpeechRecognitionError(
            "Microphone capture returned an incomplete multichannel audio frame."
        )
    if channels == 1:
        return audio
    samples = array("h")
    samples.frombytes(audio)
    if sys.byteorder != "little":
        samples.byteswap()
    mono_samples = array("h")
    for offset in range(0, len(samples), channels):
        frame_total = sum(samples[offset + index] for index in range(channels))
        mono_samples.append(int(frame_total / channels))
    if sys.byteorder != "little":
        mono_samples.byteswap()
    return mono_samples.tobytes()


class VoskCallsignRecognizer:
    """Capture bounded ALSA audio and recognize it with a constrained grammar."""

    def __init__(
        self,
        *,
        model_path: Path,
        audio_device: str,
        duration_s: int = 8,
        sample_rate: int = 16_000,
        channels: int = 1,
        model_provider: VoskModelProvider | None = None,
    ) -> None:
        if duration_s < 1:
            raise ValueError("Speech capture duration must be at least one second.")
        if sample_rate < 8_000:
            raise ValueError("Speech sample rate must be at least 8000 Hz.")
        if channels < 1 or not audio_device.strip():
            raise ValueError("Speech channels and audio device must be valid.")
        self._model_path = model_path
        self._audio_device = audio_device
        self._duration_s = duration_s
        self._sample_rate = sample_rate
        self._channels = channels
        self._model_provider = model_provider or VoskModelProvider(model_path)

    def capture_tokens(self, stop_event: Event | None = None) -> tuple[str, ...]:
        """Capture one bounded utterance, downmix it, and recognize offline."""
        cancel = stop_event or Event()
        try:
            audio = capture_alsa_pcm(
                audio_device=self._audio_device,
                duration_s=self._duration_s,
                sample_rate=self._sample_rate,
                channels=self._channels,
                stop_event=cancel,
            )
        except AudioCaptureCancelled as error:
            raise SpeechRecognitionCancelled(str(error)) from error
        except AudioCaptureError as error:
            raise SpeechRecognitionError(f"Microphone capture failed: {error}") from error

        mono_audio = _downmix_s16le_to_mono(audio, self._channels)
        if cancel.is_set():
            raise SpeechRecognitionCancelled("callsign capture cancelled")
        try:
            recognizer = self._model_provider.create_recognizer(
                self._sample_rate,
                CALLSIGN_GRAMMAR,
            )
            for offset in range(0, len(mono_audio), 8_000):
                if cancel.is_set():
                    raise SpeechRecognitionCancelled("callsign recognition cancelled")
                recognizer.AcceptWaveform(mono_audio[offset : offset + 8_000])
            if cancel.is_set():
                raise SpeechRecognitionCancelled("callsign recognition cancelled")
            result = json.loads(recognizer.FinalResult())
        except SpeechRecognitionCancelled:
            raise
        except (OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise SpeechRecognitionError(f"Vosk recognition failed: {error}") from error

        if not isinstance(result, dict) or not isinstance(result.get("text"), str):
            raise SpeechRecognitionError("Vosk returned a malformed callsign result")
        text = result["text"].strip()
        if not text:
            return ()
        return tuple(token.upper() for token in text.split())
