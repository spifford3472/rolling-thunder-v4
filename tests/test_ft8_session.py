"""Deterministic Checkpoint 7 tests for the physical QSO transmit session."""

from datetime import UTC, datetime, timedelta

import pytest

from rolling_thunder.ft8.domain import FT8Period, FT8PeriodParity, FT8QsoContext
from rolling_thunder.ft8.encoder import (
    FT8_SAMPLE_RATE_HZ,
    FT8_SLOT_SAMPLES,
    FT8EncodedMessage,
    FT8Waveform,
)
from rolling_thunder.ft8.hardware_transmit import RecordingFT8HardwareTransmitExecutor
from rolling_thunder.ft8.session import (
    FT8QsoSessionAuthorization,
    FT8QsoTransmitError,
    HardwareDigitalTransmitSession,
)
from rolling_thunder.ft8.timing import FakeFT8Clock
from rolling_thunder.ft8.transmit import FT8TransmitKind, FT8TransmitRequest


def _context(*, mode: str = "DATA") -> FT8QsoContext:
    authorized = FT8Period(100)
    return FT8QsoContext(
        local_callsign="KI5VNB",
        remote_callsign="K1ABC",
        target_audio_frequency_hz=1500,
        radio_frequency_hz=14_074_000,
        radio_band="20m",
        radio_mode=mode,
        local_grid="EM79xm",
        tx_parity=FT8PeriodParity.ODD,
        authorized_period=authorized,
        authorized_utc=authorized.start_utc + timedelta(seconds=1),
        signal_report_db=-10,
        latitude=39.5,
        longitude=-84.1,
        location_label="mobile",
    )


def _waveform(*, active_end_s: float = 12.64) -> FT8Waveform:
    active_samples = int(active_end_s * FT8_SAMPLE_RATE_HZ)
    active = b"\x01\x00" * active_samples
    silence = b"\x00\x00" * (FT8_SLOT_SAMPLES - active_samples)
    return FT8Waveform(
        encoded=FT8EncodedMessage(
            message="K1ABC KI5VNB EM79",
            packed_payload=b"0123456789",
            tones=(0,) * 79,
        ),
        base_frequency_hz=1500,
        sample_rate_hz=FT8_SAMPLE_RATE_HZ,
        pcm_s16le=active + silence,
    )


class FakeEncoder:
    def __init__(self, waveform: FT8Waveform) -> None:
        self.waveform = waveform
        self.messages: list[tuple[str, int]] = []

    def encode(self, message: str, *, base_frequency_hz: int) -> FT8Waveform:
        self.messages.append((message, base_frequency_hz))
        return self.waveform


def _request(context: FT8QsoContext) -> FT8TransmitRequest:
    return FT8TransmitRequest(
        context=context,
        kind=FT8TransmitKind.CALL,
        period=FT8Period(101),
        attempt=1,
    )


@pytest.mark.parametrize("mode", ["DATA", "USB"])
def test_session_executes_only_matching_supported_mode_qso(mode: str) -> None:
    context = _context(mode=mode)
    clock = FakeFT8Clock(FT8Period(101).start_utc + timedelta(seconds=0.10))
    encoder = FakeEncoder(_waveform())
    executor = RecordingFT8HardwareTransmitExecutor()
    session = HardwareDigitalTransmitSession(
        FT8QsoSessionAuthorization("qso-1", context),
        encoder,
        executor,
        clock,
    )

    session.request(_request(context))

    assert encoder.messages == [("K1ABC KI5VNB EM79", 1500)]
    assert len(executor.qso_requests) == 1
    physical = executor.qso_requests[0]
    assert physical.authorization.authorization_id == "qso-1"
    assert physical.authorization.context == context
    assert physical.expected_radio_frequency_hz == 14_074_000
    assert physical.expected_radio_mode == mode
    assert physical.maximum_key_down_s == pytest.approx(14.70)


def test_session_rejects_late_start_before_any_physical_request() -> None:
    context = _context()
    clock = FakeFT8Clock(FT8Period(101).start_utc + timedelta(seconds=2.20))
    executor = RecordingFT8HardwareTransmitExecutor()
    session = HardwareDigitalTransmitSession(
        FT8QsoSessionAuthorization("qso-1", context),
        FakeEncoder(_waveform()),
        executor,
        clock,
    )

    with pytest.raises(FT8QsoTransmitError, match="start window"):
        session.request(_request(context))

    assert executor.qso_requests == []


def test_session_rejects_wrong_radio_mode() -> None:
    context = _context(mode="LSB")
    clock = FakeFT8Clock(FT8Period(101).start_utc)
    executor = RecordingFT8HardwareTransmitExecutor()
    session = HardwareDigitalTransmitSession(
        FT8QsoSessionAuthorization("qso-1", context),
        FakeEncoder(_waveform()),
        executor,
        clock,
    )

    with pytest.raises(FT8QsoTransmitError, match="requires DATA or USB mode"):
        session.request(_request(context))

    assert executor.qso_requests == []


def test_session_rejects_request_from_different_context() -> None:
    context = _context()
    other = FT8QsoContext(
        local_callsign=context.local_callsign,
        remote_callsign="W1XYZ",
        target_audio_frequency_hz=context.target_audio_frequency_hz,
        radio_frequency_hz=context.radio_frequency_hz,
        radio_band=context.radio_band,
        radio_mode=context.radio_mode,
        local_grid=context.local_grid,
        tx_parity=context.tx_parity,
        authorized_period=context.authorized_period,
        authorized_utc=context.authorized_utc,
        signal_report_db=context.signal_report_db,
    )
    clock = FakeFT8Clock(FT8Period(101).start_utc)
    executor = RecordingFT8HardwareTransmitExecutor()
    session = HardwareDigitalTransmitSession(
        FT8QsoSessionAuthorization("qso-1", context),
        FakeEncoder(_waveform()),
        executor,
        clock,
    )

    with pytest.raises(FT8QsoTransmitError, match="does not match"):
        session.request(_request(other))

    assert executor.qso_requests == []


def test_session_cancel_is_idempotent_and_revokes_future_requests() -> None:
    context = _context()
    clock = FakeFT8Clock(FT8Period(101).start_utc)
    executor = RecordingFT8HardwareTransmitExecutor()
    session = HardwareDigitalTransmitSession(
        FT8QsoSessionAuthorization("qso-1", context),
        FakeEncoder(_waveform()),
        executor,
        clock,
    )

    session.cancel()
    session.cancel()

    assert executor.qso_cancel_count == 1
    with pytest.raises(FT8QsoTransmitError, match="cancelled"):
        session.request(_request(context))


def test_session_requires_current_authorized_period() -> None:
    context = _context()
    clock = FakeFT8Clock(datetime.fromtimestamp(102 * 15, tz=UTC))
    executor = RecordingFT8HardwareTransmitExecutor()
    session = HardwareDigitalTransmitSession(
        FT8QsoSessionAuthorization("qso-1", context),
        FakeEncoder(_waveform()),
        executor,
        clock,
    )

    with pytest.raises(FT8QsoTransmitError, match="no longer current"):
        session.request(_request(context))

    assert executor.qso_requests == []



class FailingEncoder:
    def encode(self, message: str, *, base_frequency_hz: int) -> FT8Waveform:
        _ = (message, base_frequency_hz)
        raise RuntimeError("synthetic encoder failure")


def test_session_encoder_failure_fails_before_physical_executor() -> None:
    context = _context()
    clock = FakeFT8Clock(FT8Period(101).start_utc)
    executor = RecordingFT8HardwareTransmitExecutor()
    session = HardwareDigitalTransmitSession(
        FT8QsoSessionAuthorization("qso-1", context),
        FailingEncoder(),
        executor,
        clock,
    )

    with pytest.raises(FT8QsoTransmitError, match="encoder failed"):
        session.request(_request(context))

    assert executor.qso_requests == []



def test_session_rejects_silent_waveform_before_physical_executor() -> None:
    context = _context()
    clock = FakeFT8Clock(FT8Period(101).start_utc)
    executor = RecordingFT8HardwareTransmitExecutor()
    session = HardwareDigitalTransmitSession(
        FT8QsoSessionAuthorization("qso-1", context),
        FakeEncoder(_waveform(active_end_s=0.0)),
        executor,
        clock,
    )

    with pytest.raises(FT8QsoTransmitError, match="no transmit-bearing samples"):
        session.request(_request(context))

    assert executor.qso_requests == []
