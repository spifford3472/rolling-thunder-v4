"""Tests for offline PCM-to-intent boundary without Vosk or audio hardware."""

from rolling_thunder.tron_commands import TronIntent
from rolling_thunder.tron_recognition import recognize_tron_pcm


class FakeRecognizer:
    def __init__(self, result: str) -> None:
        self.result = result
        self.chunks: list[bytes] = []

    def AcceptWaveform(self, audio: bytes) -> bool:
        self.chunks.append(audio)
        return False

    def FinalResult(self) -> str:
        return self.result


def test_recognizes_safe_command_with_bounded_chunks() -> None:
    fake = FakeRecognizer('{"text": "tron open map"}')
    grammars: list[tuple[str, ...]] = []

    def factory(grammar: tuple[str, ...]) -> FakeRecognizer:
        grammars.append(grammar)
        return fake

    pcm = b"\\x00\\x00" * 5_000
    assert recognize_tron_pcm(pcm, recognizer_factory=factory) == TronIntent(
        "navigate", "map"
    )
    assert len(fake.chunks) == 2
    assert sum(map(len, fake.chunks)) == len(pcm)
    assert "tron open map" in grammars[0]


def test_rejects_empty_oversized_and_partial_audio_without_initializing() -> None:
    def factory(_grammar: tuple[str, ...]) -> FakeRecognizer:
        raise AssertionError("should not initialize")

    for pcm in (b"", b"\\x00", b"\\x00" * 12):
        assert recognize_tron_pcm(
            pcm, recognizer_factory=factory, max_audio_bytes=8
        ) is None


def test_invalid_recognition_fails_closed() -> None:
    for result in (
        "invalid json", "[]", '{"text": 123}', '{"text": "tron transmit"}',
        '{"text": "open map"}', '{"text": ""}',
    ):
        assert recognize_tron_pcm(
            b"\\x00\\x00",
            recognizer_factory=lambda _grammar: FakeRecognizer(result),
        ) is None


def test_recognizer_failure_fails_closed() -> None:
    def broken(_grammar: tuple[str, ...]) -> FakeRecognizer:
        raise RuntimeError("model unavailable")

    assert recognize_tron_pcm(b"\\x00\\x00", recognizer_factory=broken) is None
