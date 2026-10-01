"""Checkpoint 6 tests for the isolated owner-test transmit boundary."""

from __future__ import annotations

import inspect
import threading
from datetime import UTC, datetime

import pytest

import rolling_thunder.ft8.qso as qso_module
from rolling_thunder.domain import Frequency, RadioConnectionState, RadioMode, RadioState
from rolling_thunder.ft8.domain import FT8Period, FT8PeriodParity, FT8QsoContext
from rolling_thunder.ft8.encoder import (
    FT8_SAMPLE_RATE_HZ,
    FT8EncodedMessage,
    FT8Waveform,
)
from rolling_thunder.ft8.hardware_transmit import (
    BoundedFT8HardwareTransmitExecutor,
    FT8HardwareTestAuthorization,
    FT8HardwareTestRequest,
    FT8QsoHardwareTransmitAuthorization,
    FT8QsoHardwareTransmitRequest,
    RecordingFT8HardwareTransmitExecutor,
)
from rolling_thunder.ft8.transmit import RecordingDigitalTransmitSession


def _waveform(*, sample_rate_hz: int = FT8_SAMPLE_RATE_HZ) -> FT8Waveform:
    return FT8Waveform(
        encoded=FT8EncodedMessage(
            message="KI5VNB TEST",
            packed_payload=b"0123456789",
            tones=(0,) * 79,
        ),
        base_frequency_hz=1500,
        sample_rate_hz=sample_rate_hz,
        pcm_s16le=b"\x00\x00" * 180_000,
    )


def _authorization() -> FT8HardwareTestAuthorization:
    return FT8HardwareTestAuthorization(
        authorization_id="owner-test-1",
        approved_at_utc=datetime(2026, 9, 30, tzinfo=UTC),
    )


def test_hardware_test_boundary_is_structurally_separate_from_qso_session() -> None:
    executor = RecordingFT8HardwareTransmitExecutor()
    qso_session = RecordingDigitalTransmitSession()

    assert hasattr(executor, "execute_test")
    assert not hasattr(executor, "request")
    assert hasattr(qso_session, "request")
    assert not hasattr(qso_session, "execute_test")
    assert "hardware_transmit" not in inspect.getsource(qso_module)


def test_recording_executor_accepts_only_explicit_test_request() -> None:
    executor = RecordingFT8HardwareTransmitExecutor()
    request = FT8HardwareTestRequest(
        authorization=_authorization(),
        waveform=_waveform(),
        maximum_key_down_s=20.0,
        expected_radio_frequency_hz=14_074_000,
        expected_radio_mode="DATA",
    )

    executor.execute_test(request)

    assert executor.requests == [request]


def test_test_authorization_requires_identity_and_aware_time() -> None:
    with pytest.raises(ValueError, match="authorization_id"):
        FT8HardwareTestAuthorization(
            authorization_id=" ",
            approved_at_utc=datetime(2026, 9, 30, tzinfo=UTC),
        )

    naive_time = datetime(2026, 9, 30, tzinfo=UTC).replace(tzinfo=None)
    with pytest.raises(ValueError, match="timezone-aware"):
        FT8HardwareTestAuthorization(
            authorization_id="owner-test-1",
            approved_at_utc=naive_time,
        )


@pytest.mark.parametrize(
    ("maximum_key_down_s", "frequency_hz", "mode", "match"),
    [
        (0.0, 14_074_000, "DATA", "maximum_key_down_s"),
        (20.0, 0, "DATA", "expected_radio_frequency_hz"),
        (20.0, 14_074_000, " ", "expected_radio_mode"),
    ],
)
def test_hardware_test_request_rejects_invalid_bounds(
    maximum_key_down_s: float,
    frequency_hz: int,
    mode: str,
    match: str,
) -> None:
    with pytest.raises(ValueError, match=match):
        FT8HardwareTestRequest(
            authorization=_authorization(),
            waveform=_waveform(),
            maximum_key_down_s=maximum_key_down_s,
            expected_radio_frequency_hz=frequency_hz,
            expected_radio_mode=mode,
        )


def test_hardware_test_request_rejects_wrong_sample_rate() -> None:
    with pytest.raises(ValueError, match="12000 Hz"):
        FT8HardwareTestRequest(
            authorization=_authorization(),
            waveform=_waveform(sample_rate_hz=48_000),
            maximum_key_down_s=20.0,
            expected_radio_frequency_hz=14_074_000,
            expected_radio_mode="DATA",
        )


def test_cancel_and_close_are_idempotent_in_hardware_free_fake() -> None:
    executor = RecordingFT8HardwareTransmitExecutor()

    executor.cancel_test()
    executor.cancel_test()
    executor.close()
    executor.close()

    assert executor.cancel_count == 2
    assert executor.close_count == 1



class _FakePtt:
    def __init__(self) -> None:
        self.events: list[str] = []

    def key(self) -> None:
        self.events.append("key")

    def release(self) -> None:
        self.events.append("release")

    def cancel(self) -> None:
        self.events.append("cancel")

    def close(self) -> None:
        self.events.append("close")


class _FakeRadio:
    def __init__(self, state: RadioState) -> None:
        self.state = state
        self.ptt = _FakePtt()
        self.refresh_count = 0

    def refresh_state(self) -> RadioState:
        self.refresh_count += 1
        return self.state

    def create_cp6_cat_ptt_capability(self) -> _FakePtt:
        return self.ptt


class _FakeAudioOutput:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.waveforms: list[FT8Waveform] = []
        self.error = error

    def play(self, waveform: FT8Waveform) -> None:
        self.waveforms.append(waveform)
        if self.error is not None:
            raise self.error


class _FakeWatchdog:
    def __init__(self, delay_s: float, callback: object) -> None:
        self.delay_s = delay_s
        self.callback = callback
        self.started = False
        self.cancelled = False

    def start(self) -> None:
        self.started = True

    def cancel(self) -> None:
        self.cancelled = True

    def fire(self) -> None:
        callback = self.callback
        assert callable(callback)
        callback()


class _WatchdogFactory:
    def __init__(self) -> None:
        self.timers: list[_FakeWatchdog] = []

    def __call__(self, delay_s: float, callback: object) -> _FakeWatchdog:
        timer = _FakeWatchdog(delay_s, callback)
        self.timers.append(timer)
        return timer


def _connected_state(
    *,
    frequency_hz: int = 14_074_000,
    mode: RadioMode = RadioMode.DATA,
) -> RadioState:
    return RadioState(
        connection_state=RadioConnectionState.CONNECTED,
        frequency=Frequency(hz=frequency_hz),
        mode=mode,
        transmitting=False,
        updated_at=datetime(2026, 9, 30, tzinfo=UTC),
    )


def _hardware_request() -> FT8HardwareTestRequest:
    return FT8HardwareTestRequest(
        authorization=_authorization(),
        waveform=_waveform(),
        maximum_key_down_s=16.0,
        expected_radio_frequency_hz=14_074_000,
        expected_radio_mode="DATA",
    )


def test_bounded_executor_verifies_keys_plays_and_releases() -> None:
    radio = _FakeRadio(_connected_state())
    audio = _FakeAudioOutput()
    watchdogs = _WatchdogFactory()
    executor = BoundedFT8HardwareTransmitExecutor(
        radio,
        audio,
        watchdog_factory=watchdogs,
    )

    executor.execute_test(_hardware_request())

    assert radio.refresh_count == 1
    assert radio.ptt.events == ["key", "release"]
    assert audio.waveforms == [_hardware_request().waveform]
    assert len(watchdogs.timers) == 1
    assert watchdogs.timers[0].delay_s == 16.0
    assert watchdogs.timers[0].started is True
    assert watchdogs.timers[0].cancelled is True


def test_bounded_executor_releases_when_playback_fails() -> None:
    radio = _FakeRadio(_connected_state())
    audio = _FakeAudioOutput(error=RuntimeError("playback failed"))
    watchdogs = _WatchdogFactory()
    executor = BoundedFT8HardwareTransmitExecutor(
        radio,
        audio,
        watchdog_factory=watchdogs,
    )

    with pytest.raises(RuntimeError, match="playback failed"):
        executor.execute_test(_hardware_request())

    assert radio.ptt.events == ["key", "release"]
    assert watchdogs.timers[0].cancelled is True


def test_watchdog_forces_release_independently() -> None:
    radio = _FakeRadio(_connected_state())
    audio = _FakeAudioOutput()
    watchdogs = _WatchdogFactory()
    executor = BoundedFT8HardwareTransmitExecutor(
        radio,
        audio,
        watchdog_factory=watchdogs,
    )

    executor.execute_test(_hardware_request())
    watchdogs.timers[0].fire()

    assert radio.ptt.events == ["key", "release", "release"]


@pytest.mark.parametrize(
    ("state", "match"),
    [
        (_connected_state(frequency_hz=7_074_000), "frequency mismatch"),
        (_connected_state(mode=RadioMode.USB), "mode mismatch"),
    ],
)
def test_bounded_executor_rejects_radio_mismatch_before_keying(
    state: RadioState,
    match: str,
) -> None:
    radio = _FakeRadio(state)
    audio = _FakeAudioOutput()
    executor = BoundedFT8HardwareTransmitExecutor(radio, audio)

    with pytest.raises(RuntimeError, match=match):
        executor.execute_test(_hardware_request())

    assert radio.ptt.events == ["release"]
    assert audio.waveforms == []


def test_cancel_and_close_force_receive_without_qso_wiring() -> None:
    radio = _FakeRadio(_connected_state())
    executor = BoundedFT8HardwareTransmitExecutor(radio, _FakeAudioOutput())

    executor.cancel_test()
    executor.close()
    executor.close()

    assert radio.ptt.events == ["cancel", "close"]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1.0, 0.0, 20.1])
def test_hardware_test_request_rejects_unsafe_keydown_bounds(value: float) -> None:
    with pytest.raises(ValueError, match="maximum_key_down_s"):
        FT8HardwareTestRequest(
            authorization=_authorization(),
            waveform=_waveform(),
            maximum_key_down_s=value,
            expected_radio_frequency_hz=14_074_000,
            expected_radio_mode="DATA",
        )



def _qso_context() -> FT8QsoContext:
    period = FT8Period(100)
    return FT8QsoContext(
        local_callsign="KI5VNB",
        remote_callsign="K1ABC",
        target_audio_frequency_hz=1500,
        radio_frequency_hz=14_074_000,
        radio_band="20m",
        radio_mode="DATA",
        local_grid="EM79xm",
        tx_parity=FT8PeriodParity.ODD,
        authorized_period=period,
        authorized_utc=period.start_utc,
        signal_report_db=-10,
    )


def _qso_hardware_request() -> FT8QsoHardwareTransmitRequest:
    context = _qso_context()
    return FT8QsoHardwareTransmitRequest(
        authorization=FT8QsoHardwareTransmitAuthorization(
            authorization_id="qso-1",
            authorized_at_utc=context.authorized_utc,
            context=context,
        ),
        waveform=_waveform(),
        maximum_key_down_s=14.5,
        expected_radio_frequency_hz=context.radio_frequency_hz,
        expected_radio_mode=context.radio_mode,
    )


def test_qso_request_uses_same_bounded_executor_without_test_authorization() -> None:
    radio = _FakeRadio(_connected_state())
    audio = _FakeAudioOutput()
    watchdogs = _WatchdogFactory()
    executor = BoundedFT8HardwareTransmitExecutor(
        radio,
        audio,
        watchdog_factory=watchdogs,
    )

    executor.execute_qso(_qso_hardware_request())

    assert radio.ptt.events == ["key", "release"]
    assert audio.waveforms == [_qso_hardware_request().waveform]
    assert watchdogs.timers[0].delay_s == 14.5


def test_qso_request_rejects_context_frequency_mismatch() -> None:
    context = _qso_context()

    with pytest.raises(ValueError, match="frequency must match"):
        FT8QsoHardwareTransmitRequest(
            authorization=FT8QsoHardwareTransmitAuthorization(
                authorization_id="qso-1",
                authorized_at_utc=context.authorized_utc,
                context=context,
            ),
            waveform=_waveform(),
            maximum_key_down_s=14.5,
            expected_radio_frequency_hz=7_074_000,
            expected_radio_mode="DATA",
        )



def test_qso_executor_rejects_disconnected_radio_before_keying() -> None:
    state = RadioState(
        connection_state=RadioConnectionState.DISCONNECTED,
        updated_at=datetime(2026, 9, 30, tzinfo=UTC),
    )
    radio = _FakeRadio(state)
    audio = _FakeAudioOutput()
    executor = BoundedFT8HardwareTransmitExecutor(radio, audio)

    with pytest.raises(RuntimeError, match="connected radio"):
        executor.execute_qso(_qso_hardware_request())

    assert radio.ptt.events == ["release"]
    assert audio.waveforms == []


class _FailingKeyPtt(_FakePtt):
    def key(self) -> None:
        self.events.append("key")
        raise RuntimeError("synthetic CAT PTT failure")


def test_qso_executor_releases_after_ptt_key_failure() -> None:
    radio = _FakeRadio(_connected_state())
    radio.ptt = _FailingKeyPtt()
    executor = BoundedFT8HardwareTransmitExecutor(radio, _FakeAudioOutput())

    with pytest.raises(RuntimeError, match="synthetic CAT PTT failure"):
        executor.execute_qso(_qso_hardware_request())

    assert radio.ptt.events == ["key", "release"]


class _BlockingAudioOutput:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    def play(self, waveform: FT8Waveform) -> None:
        _ = waveform
        self.entered.set()
        self.release.wait(2)


def test_qso_executor_prevents_overlap_and_cancel_forces_rx_while_playing() -> None:
    radio = _FakeRadio(_connected_state())
    audio = _BlockingAudioOutput()
    executor = BoundedFT8HardwareTransmitExecutor(radio, audio)
    errors: list[Exception] = []

    def run_first() -> None:
        try:
            executor.execute_qso(_qso_hardware_request())
        except RuntimeError as exc:  # pragma: no cover - assertion captures unexpected failure
            errors.append(exc)

    worker = threading.Thread(target=run_first)
    worker.start()
    assert audio.entered.wait(1)

    with pytest.raises(RuntimeError, match="already active"):
        executor.execute_qso(_qso_hardware_request())

    executor.cancel_qso()
    assert radio.ptt.events[:2] == ["key", "cancel"]

    audio.release.set()
    worker.join(1)

    assert errors == []
    assert radio.ptt.events[-1] == "release"
