"""Shared lazy Vosk provider and callsign recognition tests."""

import json
import struct
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from rolling_thunder.audio_capture import AudioCaptureCancelled
from rolling_thunder.speech_recognition import (
    SpeechRecognitionCancelled,
    SpeechRecognitionError,
    VoskCallsignRecognizer,
    VoskModelProvider,
)


class FakeVoskRecognizer:
    def __init__(self, text: str) -> None:
        self.text = text
        self.chunks: list[bytes] = []

    def AcceptWaveform(self, audio: bytes) -> bool:
        self.chunks.append(audio)
        return False

    def FinalResult(self) -> str:
        return json.dumps({"text": self.text})


def test_model_provider_is_lazy_and_loads_one_model(tmp_path, monkeypatch) -> None:
    models: list[str] = []
    recognizers: list[tuple[object, int, str]] = []

    def model(path: str) -> object:
        models.append(path)
        return object()

    def make_recognizer(shared: object, rate: int, grammar: str) -> FakeVoskRecognizer:
        recognizers.append((shared, rate, grammar))
        return FakeVoskRecognizer("kilo")

    module = SimpleNamespace(
        SetLogLevel=lambda _level: None,
        Model=model,
        KaldiRecognizer=make_recognizer,
    )
    monkeypatch.setattr(
        "rolling_thunder.speech_recognition.importlib.import_module",
        lambda _name: module,
    )
    provider = VoskModelProvider(tmp_path)
    assert models == []

    first = provider.create_recognizer(16_000, ("tron status",))
    second = provider.create_recognizer(16_000, ("alfa",))

    assert isinstance(first, FakeVoskRecognizer)
    assert isinstance(second, FakeVoskRecognizer)
    assert models == [str(tmp_path)]
    assert recognizers[0][0] is recognizers[1][0]
    assert recognizers[0][1] == recognizers[1][1] == 16_000
    assert json.loads(recognizers[0][2]) == ["tron status"]


def test_missing_model_fails_without_import(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(Path, "is_dir", lambda _path: False)
    monkeypatch.setattr(
        "rolling_thunder.speech_recognition.importlib.import_module",
        lambda _name: (_ for _ in ()).throw(AssertionError("must not import")),
    )
    with pytest.raises(SpeechRecognitionError, match="model directory"):
        VoskModelProvider(tmp_path).create_recognizer(16_000, ("tron help",))


def test_callsign_recognizer_downmixes_and_uses_lazy_provider(monkeypatch) -> None:
    stereo = struct.pack("<4h", 1000, -1000, 3000, 1000)
    monkeypatch.setattr(
        "rolling_thunder.speech_recognition.capture_alsa_pcm",
        lambda **_kwargs: stereo,
    )
    fake = FakeVoskRecognizer("kilo india five victor november bravo")

    class Provider:
        def create_recognizer(
            self, sample_rate: int, grammar: tuple[str, ...]
        ) -> FakeVoskRecognizer:
            assert sample_rate == 16_000
            assert "kilo" in grammar
            return fake

    recognizer = VoskCallsignRecognizer(
        model_path=Path("/not/loaded/here"),
        audio_device="default",
        sample_rate=16_000,
        channels=2,
        model_provider=Provider(),  # type: ignore[arg-type]
    )
    assert recognizer.capture_tokens() == (
        "KILO", "INDIA", "FIVE", "VICTOR", "NOVEMBER", "BRAVO"
    )
    assert b"".join(fake.chunks) == struct.pack("<2h", 0, 2000)


def test_callsign_capture_cancellation_is_typed(monkeypatch) -> None:
    def cancelled(**_kwargs: object) -> bytes:
        raise AudioCaptureCancelled("priority")

    monkeypatch.setattr(
        "rolling_thunder.speech_recognition.capture_alsa_pcm", cancelled
    )
    recognizer = VoskCallsignRecognizer(
        model_path=Path("/unused"),
        audio_device="default",
    )
    with pytest.raises(SpeechRecognitionCancelled):
        recognizer.capture_tokens(Event())


def test_vosk_result_must_be_well_formed(monkeypatch) -> None:
    monkeypatch.setattr(
        "rolling_thunder.speech_recognition.capture_alsa_pcm",
        lambda **_kwargs: b"\x00\x00",
    )

    class MalformedProvider:
        def create_recognizer(
            self, _sample_rate: int, _grammar: tuple[str, ...]
        ) -> FakeVoskRecognizer:
            result = FakeVoskRecognizer("")
            result.FinalResult = lambda: "[]"  # type: ignore[method-assign]
            return result

    recognizer = VoskCallsignRecognizer(
        model_path=Path("/unused"),
        audio_device="default",
        model_provider=MalformedProvider(),  # type: ignore[arg-type]
    )
    with pytest.raises(SpeechRecognitionError, match="malformed"):
        recognizer.capture_tokens()
