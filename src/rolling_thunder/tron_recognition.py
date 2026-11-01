"""Bounded offline Tron recognition from supplied PCM, without owning audio devices.

Audio capture and physical callsign priority belong to the future microphone
arbiter. This module never opens a device or dispatches an operator command.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Protocol

from rolling_thunder.tron_commands import TronIntent, command_grammar, parse_tron_command


class OfflineRecognizer(Protocol):
    """Subset of the Vosk recognizer used for finalized offline utterances."""

    def AcceptWaveform(self, audio: bytes) -> bool: ...

    def FinalResult(self) -> str: ...


RecognizerFactory = Callable[[tuple[str, ...]], OfflineRecognizer]


def recognize_tron_pcm(
    pcm: bytes,
    *,
    recognizer_factory: RecognizerFactory,
    max_audio_bytes: int = 256_000,
) -> TronIntent | None:
    """Recognize one bounded mono S16_LE utterance; reject failures safely.

    The caller must guarantee a 16 kHz mono recording and exclusive microphone
    ownership. The default limit is eight seconds of S16_LE at 16 kHz.
    """
    if max_audio_bytes < 2:
        raise ValueError("max_audio_bytes must allow at least one audio sample")
    if not pcm or len(pcm) > max_audio_bytes or len(pcm) % 2:
        return None

    try:
        recognizer = recognizer_factory(command_grammar())
        for offset in range(0, len(pcm), 8_000):
            recognizer.AcceptWaveform(pcm[offset : offset + 8_000])
        result = json.loads(recognizer.FinalResult())
    except (RuntimeError, OSError, ValueError, TypeError, json.JSONDecodeError):
        return None

    if not isinstance(result, dict):
        return None
    transcript = result.get("text")
    if not isinstance(transcript, str):
        return None
    return parse_tron_command(transcript)
