"""Bounded ALSA subprocess cleanup tests using mocked pipes and process signals."""

from collections.abc import Iterator
from threading import Event

import pytest

from rolling_thunder.audio_capture import (
    AudioCaptureCancelled,
    AudioCaptureError,
    capture_alsa_pcm,
)


class FakePipe:
    def fileno(self) -> int:
        return 42

    def close(self) -> None:
        pass


class FakeProcess:
    def __init__(self) -> None:
        self.pid = 123
        self.stdout = FakePipe()
        self.stderr = None
        self.reaped = False
        self.return_code = 0

    def poll(self) -> int | None:
        return None if not self.reaped else self.return_code

    def wait(self, timeout: float | None = None) -> int:
        self.reaped = True
        return self.return_code


@pytest.fixture
def fake_process(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeProcess]:
    process = FakeProcess()
    monkeypatch.setattr(
        "rolling_thunder.audio_capture.subprocess.Popen",
        lambda *_args, **_kwargs: process,
    )
    monkeypatch.setattr(
        "rolling_thunder.audio_capture.os.killpg",
        lambda _pid, _sig: None,
    )
    monkeypatch.setattr(
        "rolling_thunder.audio_capture.select.select",
        lambda readers, _writers, _errors, _timeout: (readers, [], []),
    )
    yield process


def test_captures_bounded_signed_16_bit_pcm(fake_process: FakeProcess, monkeypatch) -> None:
    chunks = iter((b"\x01\x00\x02\x00", b""))
    monkeypatch.setattr(
        "rolling_thunder.audio_capture.os.read",
        lambda _fd, _size: next(chunks),
    )

    pcm = capture_alsa_pcm(
        audio_device="plughw:CARD=Array,DEV=0",
        duration_s=1,
        sample_rate=16_000,
        channels=1,
        stop_event=Event(),
    )

    assert pcm == b"\x01\x00\x02\x00"
    assert fake_process.reaped


def test_cancellation_terminates_and_reaps_subprocess(
    fake_process: FakeProcess,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop = Event()
    killed: list[int] = []
    monkeypatch.setattr(
        "rolling_thunder.audio_capture.os.killpg",
        lambda _pid, sig: killed.append(sig),
    )

    def read_and_cancel(_fd: int, _size: int) -> bytes:
        stop.set()
        return b"\x00\x00"

    monkeypatch.setattr("rolling_thunder.audio_capture.os.read", read_and_cancel)

    with pytest.raises(AudioCaptureCancelled):
        capture_alsa_pcm(
            audio_device="default",
            duration_s=1,
            sample_rate=16_000,
            channels=1,
            stop_event=stop,
        )

    assert fake_process.reaped
    assert killed


def test_audio_limit_rejects_excess_and_reaps_process(
    fake_process: FakeProcess,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "rolling_thunder.audio_capture.os.read",
        lambda _fd, _size: b"\x00" * 6,
    )

    with pytest.raises(AudioCaptureError, match="byte limit"):
        capture_alsa_pcm(
            audio_device="default",
            duration_s=1,
            sample_rate=16_000,
            channels=1,
            stop_event=Event(),
            max_bytes=4,
        )

    assert fake_process.reaped


def test_disconnected_device_error_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "rolling_thunder.audio_capture.subprocess.Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError()),
    )

    with pytest.raises(AudioCaptureError, match="arecord was not found"):
        capture_alsa_pcm(
            audio_device="default",
            duration_s=1,
            sample_rate=16_000,
            channels=1,
            stop_event=Event(),
        )
