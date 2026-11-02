"""Bounded offline Tron recognition from mono PCM, without device ownership."""

from __future__ import annotations

import json
from collections.abc import Callable
from threading import Event
from typing import Protocol

from rolling_thunder.tron_commands import TronIntent, command_grammar, parse_tron_command


class OfflineRecognizer(Protocol):
    """Subset of the Vosk recognizer used for finalized offline utterances."""

    def AcceptWaveform(self, audio: bytes) -> bool: ...
    def FinalResult(self) -> str: ...


RecognizerFactory = Callable[[tuple[str, ...]], OfflineRecognizer]
RecognitionErrorHandler = Callable[[str], None]


def _report_error(handler: RecognitionErrorHandler | None, message: str) -> None:
    if handler is not None:
        handler(message[:240])


def recognize_tron_pcm(
    pcm: bytes,
    *,
    recognizer_factory: RecognizerFactory,
    max_audio_bytes: int = 256_000,
    stop_event: Event | None = None,
    on_error: RecognitionErrorHandler | None = None,
) -> TronIntent | None:
    """Recognize one bounded mono 16 kHz S16_LE utterance; fail closed."""
    if max_audio_bytes < 2:
        raise ValueError("max_audio_bytes must allow at least one audio sample")
    if not pcm or len(pcm) > max_audio_bytes or len(pcm) % 2:
        return None
    if stop_event is not None and stop_event.is_set():
        return None
    try:
        recognizer = recognizer_factory(command_grammar())
        for offset in range(0, len(pcm), 8_000):
            if stop_event is not None and stop_event.is_set():
                return None
            recognizer.AcceptWaveform(pcm[offset : offset + 8_000])
        if stop_event is not None and stop_event.is_set():
            return None
        result = json.loads(recognizer.FinalResult())
    except (RuntimeError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        _report_error(on_error, str(error))
        return None
    if not isinstance(result, dict):
        _report_error(on_error, "Vosk returned a malformed result")
        return None
    transcript = result.get("text")
    if not isinstance(transcript, str):
        _report_error(on_error, "Vosk returned a result without text")
        return None
    return parse_tron_command(transcript)
