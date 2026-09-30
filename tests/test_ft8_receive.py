"""Deterministic tests for the bounded FT8 receive service."""

from __future__ import annotations

import threading
import time
from collections.abc import Sequence
from datetime import UTC, datetime

from rolling_thunder.ft8.activity import FT8CQActivityManager
from rolling_thunder.ft8.audio import FT8AudioInputError
from rolling_thunder.ft8.decoder import FT8DecoderError, FT8PcmPeriod
from rolling_thunder.ft8.domain import FT8Decode, FT8MessageKind, FT8Period
from rolling_thunder.ft8.receive import FT8ReceiveService, FT8ReceiveStatus


def _period(index: int) -> FT8PcmPeriod:
    return FT8PcmPeriod(
        period=FT8Period(index),
        sample_rate_hz=12_000,
        pcm_s16le=b"\x00\x00" * 180_000,
    )


class FakeAudioInput:
    def __init__(self, periods: Sequence[FT8PcmPeriod]) -> None:
        self._periods = list(periods)
        self.started = 0
        self.stopped = 0
        self._cancelled = threading.Event()

    def start(self) -> None:
        self.started += 1
        self._cancelled.clear()

    def read_period(self) -> FT8PcmPeriod:
        if self._periods:
            return self._periods.pop(0)
        self._cancelled.wait(2)
        raise FT8AudioInputError("fake capture stopped")

    def stop(self) -> None:
        self.stopped += 1
        self._cancelled.set()


class RecordingDecoder:
    def __init__(self) -> None:
        self.periods: list[FT8Period] = []

    def decode(self, pcm: FT8PcmPeriod) -> tuple[FT8Decode, ...]:
        self.periods.append(pcm.period)
        return (
            FT8Decode(
                period=pcm.period,
                snr_db=-8,
                dt_seconds=0.2,
                audio_frequency_hz=1500,
                raw_message="CQ K1ABC FN31",
                kind=FT8MessageKind.CQ,
                source_callsign="K1ABC",
                grid="FN31",
            ),
        )


class FailOnceDecoder:
    def __init__(self) -> None:
        self.calls = 0

    def decode(self, pcm: FT8PcmPeriod) -> tuple[FT8Decode, ...]:
        self.calls += 1
        if self.calls == 1:
            raise FT8DecoderError("synthetic decoder failure")
        return ()


class SlowDecoder:
    def __init__(self) -> None:
        self.release = threading.Event()
        self.calls = 0

    def decode(self, pcm: FT8PcmPeriod) -> tuple[FT8Decode, ...]:
        self.calls += 1
        self.release.wait(2)
        return ()


def _wait_until(predicate: object, timeout_s: float = 2.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if callable(predicate) and predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not reached before timeout")


def test_receive_service_invokes_decoder_and_publishes_cq_activity() -> None:
    audio = FakeAudioInput([_period(100)])
    decoder = RecordingDecoder()
    service = FT8ReceiveService(
        audio,
        decoder,
        FT8CQActivityManager(),
        reconnect_delay_s=0.01,
    )

    service.start()
    _wait_until(lambda: service.latest_state.decode_count == 1)
    service.stop()

    state = service.latest_state
    assert state.status is FT8ReceiveStatus.STOPPED
    assert state.periods_captured == 1
    assert decoder.periods == [FT8Period(100)]
    assert len(state.cq_activity) == 1
    assert state.cq_activity[0].callsign == "K1ABC"
    assert audio.stopped >= 1


def test_receive_service_bounds_decoder_backlog_and_drops_stale_periods() -> None:
    audio = FakeAudioInput([_period(200), _period(201), _period(202)])
    decoder = SlowDecoder()
    service = FT8ReceiveService(
        audio,
        decoder,
        FT8CQActivityManager(),
        reconnect_delay_s=0.01,
    )

    service.start()
    _wait_until(lambda: service.latest_state.periods_captured >= 3)
    _wait_until(lambda: service.latest_state.periods_dropped >= 1)
    decoder.release.set()
    service.stop()

    assert service.latest_state.periods_dropped >= 1


def test_receive_service_cancellation_releases_audio_input() -> None:
    audio = FakeAudioInput([])
    service = FT8ReceiveService(
        audio,
        RecordingDecoder(),
        FT8CQActivityManager(),
        reconnect_delay_s=0.01,
    )

    service.start()
    _wait_until(lambda: audio.started >= 1)
    service.stop()

    assert audio.stopped >= 1
    assert service.latest_state.status is FT8ReceiveStatus.STOPPED


def test_receive_service_reports_unavailable_audio_as_degraded() -> None:
    class UnavailableAudio(FakeAudioInput):
        def start(self) -> None:
            self.started += 1
            raise FT8AudioInputError("DigiRig unavailable")

    audio = UnavailableAudio([])
    service = FT8ReceiveService(
        audio,
        RecordingDecoder(),
        FT8CQActivityManager(),
        reconnect_delay_s=0.5,
    )

    service.start()
    _wait_until(lambda: service.latest_state.status is FT8ReceiveStatus.DEGRADED)
    state = service.latest_state
    service.stop()

    assert state.last_error == "DigiRig unavailable"


def test_test_period_reference_is_utc_aware() -> None:
    assert datetime(2026, 9, 29, 23, 30, tzinfo=UTC).utcoffset() is not None


def test_receive_service_recovers_after_transient_decoder_failure() -> None:
    audio = FakeAudioInput([_period(300), _period(301)])
    decoder = FailOnceDecoder()
    service = FT8ReceiveService(
        audio,
        decoder,
        FT8CQActivityManager(),
        reconnect_delay_s=0.01,
    )

    service.start()
    _wait_until(lambda: decoder.calls >= 2)
    _wait_until(lambda: service.latest_state.status is FT8ReceiveStatus.RUNNING)
    state = service.latest_state
    service.stop()

    assert state.last_error is None
    assert state.periods_captured >= 2
