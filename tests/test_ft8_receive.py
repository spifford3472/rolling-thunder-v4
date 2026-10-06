"""Deterministic tests for the bounded FT8 receive service."""

from __future__ import annotations

import threading
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from rolling_thunder.ft8.activity import FT8CQActivityManager
from rolling_thunder.ft8.audio import FT8AudioInputError
from rolling_thunder.ft8.decoder import FT8DecoderError, FT8PcmPeriod
from rolling_thunder.ft8.diagnostics import FT8ClockQuality, NTPClockStatus
from rolling_thunder.ft8.domain import FT8Decode, FT8MessageKind, FT8Period
from rolling_thunder.ft8.receive import (
    BoundedFT8PeriodRecorder,
    FT8ReceiveService,
    FT8ReceiveStatus,
)


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


class AddressedCallDecoder:
    def decode(self, pcm: FT8PcmPeriod) -> tuple[FT8Decode, ...]:
        return (
            FT8Decode(
                period=pcm.period,
                snr_db=-12,
                dt_seconds=0.1,
                audio_frequency_hz=1400,
                raw_message="KI5VNB K1OLD -10",
                kind=FT8MessageKind.REPORT,
                source_callsign="K1OLD",
                destination_callsign="KI5VNB",
                report_db=-10,
            ),
            FT8Decode(
                period=pcm.period,
                snr_db=-7,
                dt_seconds=0.2,
                audio_frequency_hz=1600,
                raw_message="KI5VNB W1NEW FN42",
                kind=FT8MessageKind.OTHER,
                source_callsign="W1NEW",
                destination_callsign="KI5VNB",
                grid="FN42",
            ),
            FT8Decode(
                period=pcm.period,
                snr_db=-3,
                dt_seconds=0.3,
                audio_frequency_hz=1800,
                raw_message="N0XYZ K2NOPE -02",
                kind=FT8MessageKind.REPORT,
                source_callsign="K2NOPE",
                destination_callsign="N0XYZ",
                report_db=-2,
            ),
        )


class FailOnceDecoder:
    def __init__(self) -> None:
        self.calls = 0
        self.first_failure = threading.Event()

    def decode(self, pcm: FT8PcmPeriod) -> tuple[FT8Decode, ...]:
        self.calls += 1
        if self.calls == 1:
            self.first_failure.set()
            raise FT8DecoderError("synthetic decoder failure")
        return ()


class GatedSecondPeriodAudioInput(FakeAudioInput):
    def __init__(
        self,
        periods: Sequence[FT8PcmPeriod],
        *,
        release_second: threading.Event,
    ) -> None:
        super().__init__(periods)
        self._release_second = release_second
        self._reads = 0

    def read_period(self) -> FT8PcmPeriod:
        self._reads += 1
        if self._reads == 2 and not self._release_second.wait(2):
            raise FT8AudioInputError("second test period was not released")
        return super().read_period()


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


def test_receive_service_publishes_most_recent_call_to_configured_local_callsign() -> None:
    service = FT8ReceiveService(
        FakeAudioInput([_period(110)]),
        AddressedCallDecoder(),
        FT8CQActivityManager(),
        reconnect_delay_s=0.01,
        local_callsign="KI5VNB",
    )

    service.start()
    _wait_until(lambda: service.latest_state.decode_count == 3)
    state = service.latest_state
    service.stop()

    assert state.incoming_call is not None
    assert state.incoming_call.callsign == "W1NEW"
    assert state.incoming_call.snr_db == -7
    assert state.incoming_call.grid == "FN42"


def test_receive_service_clear_cq_activity_removes_old_band_rows() -> None:
    audio = FakeAudioInput([_period(150)])
    service = FT8ReceiveService(
        audio,
        RecordingDecoder(),
        FT8CQActivityManager(),
        reconnect_delay_s=0.01,
    )

    service.start()
    _wait_until(lambda: len(service.latest_state.cq_activity) == 1)

    service.clear_cq_activity()

    assert service.latest_state.cq_activity == ()
    service.stop()


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
    decoder = FailOnceDecoder()
    audio = GatedSecondPeriodAudioInput(
        [_period(300), _period(301)],
        release_second=decoder.first_failure,
    )
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


class RecordingObserver:
    def __init__(self) -> None:
        self.decode_batches: list[tuple[FT8Decode, ...]] = []
        self.errors: list[str] = []

    def on_decodes(self, decodes: tuple[FT8Decode, ...]) -> None:
        self.decode_batches.append(decodes)

    def on_receive_error(self, detail: str) -> None:
        self.errors.append(detail)


def test_receive_service_fans_out_normalized_decodes_to_observer() -> None:
    observer = RecordingObserver()
    service = FT8ReceiveService(
        FakeAudioInput([_period(400)]),
        RecordingDecoder(),
        FT8CQActivityManager(),
        reconnect_delay_s=0.01,
        observer=observer,
    )

    service.start()
    _wait_until(lambda: bool(observer.decode_batches))
    service.stop()

    assert len(observer.decode_batches) == 1
    assert observer.decode_batches[0][0].source_callsign == "K1ABC"


def test_receive_service_reports_decoder_failure_to_observer() -> None:
    observer = RecordingObserver()
    decoder = FailOnceDecoder()
    audio = GatedSecondPeriodAudioInput(
        [_period(500), _period(501)],
        release_second=decoder.first_failure,
    )
    service = FT8ReceiveService(
        audio,
        decoder,
        FT8CQActivityManager(),
        reconnect_delay_s=0.01,
        observer=observer,
    )

    service.start()
    _wait_until(lambda: bool(observer.errors))
    service.stop()

    assert observer.errors[0] == "synthetic decoder failure"


def test_pcm_recorder_uses_only_three_stable_storage_slots(tmp_path: Path) -> None:
    recorder = BoundedFT8PeriodRecorder(tmp_path, maximum_periods=3)

    paths = [recorder.save(_period(index)) for index in range(4)]

    assert paths[-1] is None
    assert recorder.saved == 3
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "ft8-period-01.wav",
        "ft8-period-02.wav",
        "ft8-period-03.wav",
    ]


def test_clock_diagnostic_failure_does_not_interrupt_receive_capture() -> None:
    def failed_ntp_probe() -> NTPClockStatus:
        raise RuntimeError("synthetic chrony failure")

    service = FT8ReceiveService(
        FakeAudioInput([]),
        RecordingDecoder(),
        FT8CQActivityManager(),
        ntp_status=failed_ntp_probe,
    )

    service._record_capture(_period(600))

    state = service.latest_state
    assert state.periods_captured == 1
    assert state.last_clock is not None
    assert state.last_clock.quality is FT8ClockQuality.UNVERIFIED
    assert state.last_diagnostic_error == (
        "clock readiness diagnostic failed: synthetic chrony failure"
    )
