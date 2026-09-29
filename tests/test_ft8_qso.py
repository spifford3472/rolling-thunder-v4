"""Tests for the hardware-free FT8 QSO state machine."""

from datetime import UTC, datetime

from rolling_thunder.ft8.domain import (
    FT8Decode,
    FT8MessageKind,
    FT8Period,
    FT8PeriodParity,
    FT8QsoContext,
    FT8QsoState,
)
from rolling_thunder.ft8.qso import FT8QsoController
from rolling_thunder.ft8.transmit import FT8TransmitKind, RecordingDigitalTransmitSession


def _context() -> FT8QsoContext:
    return FT8QsoContext(
        local_callsign="KI5VNB",
        remote_callsign="K1ABC",
        target_audio_frequency_hz=1500,
        radio_frequency_hz=14_074_000,
        radio_band="20m",
        radio_mode="DIG-U",
        local_grid="EM79xm",
        tx_parity=FT8PeriodParity.ODD,
        authorized_period=FT8Period(index=100),
        authorized_utc=datetime.fromtimestamp(1501, tz=UTC),
        latitude=39.5,
        longitude=-84.1,
        location_label="mobile",
    )


def _decode(
    period: int,
    kind: FT8MessageKind,
    *,
    source: str = "K1ABC",
    destination: str | None = "KI5VNB",
) -> FT8Decode:
    return FT8Decode(
        period=FT8Period(index=period),
        snr_db=-10,
        dt_seconds=0.1,
        audio_frequency_hz=1500,
        raw_message=f"{source} {destination or ''} {kind.value}",
        kind=kind,
        source_callsign=source,
        destination_callsign=destination,
        report_db=-10 if kind in {FT8MessageKind.REPORT, FT8MessageKind.R_REPORT} else None,
    )


def _started() -> tuple[FT8QsoController, RecordingDigitalTransmitSession]:
    session = RecordingDigitalTransmitSession()
    controller = FT8QsoController(session)
    controller.authorize(_context())
    assert controller.state is FT8QsoState.AUTHORIZED
    controller.start()
    return controller, session


def test_synthetic_exchange_completes_without_starting_second_qso() -> None:
    controller, session = _started()

    controller.on_period(FT8Period(index=101))
    assert controller.state is FT8QsoState.WAIT_REPORT
    assert session.requests[-1].kind is FT8TransmitKind.CALL

    controller.on_decode(_decode(102, FT8MessageKind.REPORT))
    assert controller.state is FT8QsoState.TX_REPORT
    assert controller.attempt_count == 0
    controller.on_period(FT8Period(index=103))
    assert session.requests[-1].kind is FT8TransmitKind.REPORT

    controller.on_decode(_decode(104, FT8MessageKind.R_REPORT))
    controller.on_period(FT8Period(index=105))
    assert session.requests[-1].kind is FT8TransmitKind.R_REPORT

    controller.on_decode(_decode(106, FT8MessageKind.ACK_73))
    controller.on_period(FT8Period(index=107))

    assert controller.state is FT8QsoState.COMPLETED
    assert session.requests[-1].kind is FT8TransmitKind.SEVENTY_THREE
    request_count = len(session.requests)
    controller.on_period(FT8Period(index=109))
    controller.on_decode(_decode(108, FT8MessageKind.REPORT))
    assert len(session.requests) == request_count
    assert controller.context is not None


def test_six_attempts_apply_to_one_unchanged_state_then_exhaust() -> None:
    controller, session = _started()

    for period_index in (101, 103, 105, 107, 109, 111):
        controller.on_period(FT8Period(index=period_index))

    assert len(session.requests) == 6
    assert [request.attempt for request in session.requests] == [1, 2, 3, 4, 5, 6]
    assert controller.state is FT8QsoState.WAIT_REPORT

    controller.on_period(FT8Period(index=113))

    assert controller.state is FT8QsoState.RETRY_EXHAUSTED
    assert len(session.requests) == 6
    assert session.cancel_count == 1


def test_valid_advancement_resets_retry_budget_for_next_message() -> None:
    controller, session = _started()
    controller.on_period(FT8Period(index=101))
    controller.on_period(FT8Period(index=103))
    assert controller.attempt_count == 2

    controller.on_decode(_decode(104, FT8MessageKind.REPORT))
    assert controller.attempt_count == 0
    controller.on_period(FT8Period(index=105))

    assert session.requests[-1].kind is FT8TransmitKind.REPORT
    assert session.requests[-1].attempt == 1


def test_unrelated_stale_duplicate_and_wrong_parity_decodes_are_ignored() -> None:
    controller, _ = _started()
    controller.on_period(FT8Period(index=101))

    controller.on_decode(_decode(102, FT8MessageKind.REPORT, source="W1XYZ"))
    controller.on_decode(_decode(100, FT8MessageKind.REPORT))
    controller.on_decode(_decode(103, FT8MessageKind.REPORT))
    assert controller.state is FT8QsoState.WAIT_REPORT

    controller.on_decode(_decode(102, FT8MessageKind.REPORT))
    assert controller.state is FT8QsoState.TX_REPORT
    controller.on_decode(_decode(102, FT8MessageKind.R_REPORT))
    assert controller.state is FT8QsoState.TX_REPORT


def test_manual_abort_is_idempotent_and_prevents_future_requests() -> None:
    controller, session = _started()
    controller.on_period(FT8Period(index=101))

    controller.abort()
    controller.abort()
    controller.on_period(FT8Period(index=103))
    controller.on_decode(_decode(102, FT8MessageKind.REPORT))

    assert controller.state is FT8QsoState.ABORTED
    assert session.cancel_count == 1
    assert len(session.requests) == 1


def test_error_is_terminal_and_explicit_reset_clears_authorization() -> None:
    controller, session = _started()
    controller.fail()

    assert controller.state is FT8QsoState.ERROR
    assert session.cancel_count == 1
    controller.on_period(FT8Period(index=101))
    assert session.requests == []

    controller.reset()

    assert controller.state is FT8QsoState.IDLE
    assert controller.context is None
    assert controller.attempt_count == 0
