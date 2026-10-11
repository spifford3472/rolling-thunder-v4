"""Tests for the hardware-free FT8 QSO state machine."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from rolling_thunder.ft8.domain import (
    FT8Decode,
    FT8IncomingCall,
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
        radio_mode="DATA",
        local_grid="EM79xm",
        tx_parity=FT8PeriodParity.ODD,
        authorized_period=FT8Period(index=100),
        authorized_utc=datetime.fromtimestamp(1501, tz=UTC),
        signal_report_db=-10,
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


def _responder_context(kind: FT8MessageKind) -> FT8QsoContext:
    report_db = -3 if kind is FT8MessageKind.REPORT else None
    callsign = "K0BQB" if report_db is not None else "W4YRL"
    grid = None if report_db is not None else "EL99"
    raw_payload = "-03" if report_db is not None else "EL99"
    return replace(
        _context(),
        remote_callsign=callsign,
        signal_report_db=-7,
        remote_grid=grid,
        responder_inbound=FT8IncomingCall(
            callsign=callsign,
            period=FT8Period(100),
            snr_db=-7,
            dt_seconds=0.1,
            audio_frequency_hz=1500,
            kind=kind,
            grid=grid,
            report_db=report_db,
            raw_message=f"KI5VNB {callsign} {raw_payload}",
        ),
    )


def test_grid_initiated_responder_sends_report_then_waits_for_r_report() -> None:
    session = RecordingDigitalTransmitSession()
    controller = FT8QsoController(session)
    controller.authorize(_responder_context(FT8MessageKind.ADDRESSED_GRID))
    controller.start()

    assert controller.state is FT8QsoState.TX_REPORT
    assert session.requests == []

    controller.on_period(FT8Period(101))

    assert session.requests[-1].kind is FT8TransmitKind.REPORT
    assert controller.state is FT8QsoState.WAIT_R_REPORT
    controller.on_decode(_decode(102, FT8MessageKind.R_REPORT, source="W4YRL"))
    controller.on_period(FT8Period(103))
    assert session.requests[-1].kind is FT8TransmitKind.SEVENTY_THREE
    assert controller.state is FT8QsoState.COMPLETED


def test_report_initiated_responder_sends_r_report_then_waits_for_ack() -> None:
    session = RecordingDigitalTransmitSession()
    controller = FT8QsoController(session)
    controller.authorize(_responder_context(FT8MessageKind.REPORT))
    controller.start()

    assert controller.state is FT8QsoState.TX_R_REPORT
    assert session.requests == []

    controller.on_period(FT8Period(101))

    assert session.requests[-1].kind is FT8TransmitKind.R_REPORT
    assert controller.state is FT8QsoState.WAIT_73
    controller.on_decode(_decode(102, FT8MessageKind.ACK_73, source="K0BQB"))
    controller.on_period(FT8Period(103))
    assert session.requests[-1].kind is FT8TransmitKind.SEVENTY_THREE
    assert controller.state is FT8QsoState.COMPLETED


def test_synthetic_exchange_completes_without_starting_second_qso() -> None:
    controller, session = _started()

    controller.on_period(FT8Period(index=101))
    assert controller.state is FT8QsoState.WAIT_REPORT
    assert session.requests[-1].kind is FT8TransmitKind.CALL

    controller.on_decode(_decode(102, FT8MessageKind.REPORT))
    assert controller.state is FT8QsoState.TX_R_REPORT
    assert controller.attempt_count == 0
    controller.on_period(FT8Period(index=103))
    assert session.requests[-1].kind is FT8TransmitKind.R_REPORT

    controller.on_decode(_decode(104, FT8MessageKind.ACK_73))
    controller.on_period(FT8Period(index=105))

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

    assert session.requests[-1].kind is FT8TransmitKind.R_REPORT
    assert session.requests[-1].attempt == 1


def test_unrelated_stale_duplicate_and_wrong_parity_decodes_are_ignored() -> None:
    controller, _ = _started()
    controller.on_period(FT8Period(index=101))

    controller.on_decode(_decode(102, FT8MessageKind.REPORT, source="W1XYZ"))
    controller.on_decode(_decode(100, FT8MessageKind.REPORT))
    controller.on_decode(_decode(103, FT8MessageKind.REPORT))
    assert controller.state is FT8QsoState.WAIT_REPORT

    controller.on_decode(_decode(102, FT8MessageKind.REPORT))
    assert controller.state is FT8QsoState.TX_R_REPORT
    controller.on_decode(_decode(102, FT8MessageKind.R_REPORT))
    assert controller.state is FT8QsoState.TX_R_REPORT


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



def test_wrong_destination_decode_cannot_advance_qso() -> None:
    controller, _ = _started()
    controller.on_period(FT8Period(index=101))

    controller.on_decode(
        _decode(102, FT8MessageKind.REPORT, destination="W9ABC")
    )

    assert controller.state is FT8QsoState.WAIT_REPORT


@pytest.mark.parametrize("final_text", ["RRR", "RR73", "73"])
def test_all_supported_final_ack_variants_complete_same_exchange(final_text: str) -> None:
    controller, session = _started()
    controller.on_period(FT8Period(index=101))
    controller.on_decode(_decode(102, FT8MessageKind.REPORT))
    controller.on_period(FT8Period(index=103))

    final = _decode(104, FT8MessageKind.ACK_73)
    final = FT8Decode(
        period=final.period,
        snr_db=final.snr_db,
        dt_seconds=final.dt_seconds,
        audio_frequency_hz=final.audio_frequency_hz,
        raw_message=f"KI5VNB K1ABC {final_text}",
        kind=FT8MessageKind.ACK_73,
        source_callsign=final.source_callsign,
        destination_callsign=final.destination_callsign,
    )
    controller.on_decode(final)
    controller.on_period(FT8Period(index=105))

    assert controller.state is FT8QsoState.COMPLETED
    assert session.requests[-1].kind is FT8TransmitKind.SEVENTY_THREE


def test_r_report_phase_has_its_own_six_attempt_retry_budget() -> None:
    controller, session = _started()
    controller.on_period(FT8Period(index=101))
    controller.on_decode(_decode(102, FT8MessageKind.REPORT))

    for period_index in (103, 105, 107, 109, 111, 113):
        controller.on_period(FT8Period(index=period_index))

    r_reports = [
        request
        for request in session.requests
        if request.kind is FT8TransmitKind.R_REPORT
    ]
    assert len(r_reports) == 6
    assert [request.attempt for request in r_reports] == [1, 2, 3, 4, 5, 6]

    controller.on_period(FT8Period(index=115))

    assert controller.state is FT8QsoState.RETRY_EXHAUSTED
    assert session.cancel_count == 1


def test_out_of_order_final_ack_before_report_advancement_is_ignored() -> None:
    controller, _ = _started()
    controller.on_period(FT8Period(index=101))

    controller.on_decode(_decode(102, FT8MessageKind.ACK_73))

    assert controller.state is FT8QsoState.WAIT_REPORT


@pytest.mark.parametrize(
    "prepare",
    [
        "authorized",
        "wait_tx_call",
        "wait_report",
        "tx_r_report",
        "wait_73",
        "tx_73",
    ],
)
def test_abort_is_safe_from_every_reachable_nonterminal_state(prepare: str) -> None:
    session = RecordingDigitalTransmitSession()
    controller = FT8QsoController(session)
    controller.authorize(_context())

    if prepare == "authorized":
        pass
    else:
        controller.start()
        if prepare in {"wait_report", "tx_r_report", "wait_73", "tx_73"}:
            controller.on_period(FT8Period(index=101))
        if prepare in {"tx_r_report", "wait_73", "tx_73"}:
            controller.on_decode(_decode(102, FT8MessageKind.REPORT))
        if prepare in {"wait_73", "tx_73"}:
            controller.on_period(FT8Period(index=103))
        if prepare == "tx_73":
            controller.on_decode(_decode(104, FT8MessageKind.ACK_73))

    controller.abort()
    controller.abort()

    assert controller.state is FT8QsoState.ABORTED
    assert session.cancel_count == 1



def test_missing_destination_decode_cannot_advance_qso() -> None:
    controller, _ = _started()
    controller.on_period(FT8Period(index=101))

    controller.on_decode(_decode(102, FT8MessageKind.REPORT, destination=None))

    assert controller.state is FT8QsoState.WAIT_REPORT


def test_cp31_busy_target_integrated_exchange_and_bound() -> None:
    """Only source-attributed third-party replies grant two fixed, power-neutral calls."""
    from rolling_thunder.ft8.target_activity import FT8TargetActivityTracker

    tracker = FT8TargetActivityTracker(local_callsign="KI5VNB")
    tracker.select("K1ABC")
    controller, session = _started()  # Explicit selection/authorization is separate.
    cq = _decode(100, FT8MessageKind.CQ, destination=None)
    tracker.observe((cq,), FT8Period(100))
    controller.observe_target_activity(tracker.snapshot(FT8Period(101)), FT8Period(101))
    caller = _decode(102, FT8MessageKind.ADDRESSED_GRID, source="W1XYZ", destination="K1ABC")
    tracker.observe((caller,), FT8Period(102))
    controller.observe_target_activity(tracker.snapshot(FT8Period(103)), FT8Period(103))
    for index in (101, 103):
        controller.on_period(FT8Period(index))
    assert controller.busy_extension_attempts == 0
    for kind, index in ((FT8MessageKind.ADDRESSED_GRID, 104), (FT8MessageKind.REPORT, 106),
                        (FT8MessageKind.R_REPORT, 108), (FT8MessageKind.ACK_73, 110)):
        reply = _decode(index, kind, source="K1ABC", destination="W1XYZ")
        tracker.observe((reply,), FT8Period(index))
        controller.observe_target_activity(tracker.snapshot(FT8Period(index + 1)), FT8Period(index + 1))
        controller.on_period(FT8Period(index + 1))
    assert controller.state is FT8QsoState.WAIT_REPORT  # Third-party 73 is not our completion.
    controller.on_period(FT8Period(113))  # Stale activity cannot revoke earned allowance.
    controller.on_period(FT8Period(115))
    assert [request.attempt for request in session.requests] == list(range(1, 9))
    assert [request.busy_extension for request in session.requests] == [False] * 6 + [True, True]
    assert controller.busy_extension_attempts == 2
    controller.on_period(FT8Period(117))
    assert controller.state is FT8QsoState.RETRY_EXHAUSTED
    assert len(session.requests) == 8  # No ninth transmission.


def test_cp31_busy_extension_rejects_stale_wrong_target_and_resets_on_phase() -> None:
    from rolling_thunder.ft8.target_activity import TargetActivity, TargetActivityKind

    controller, session = _started()
    def activity(callsign: str, period: int, source: bool = True) -> TargetActivity:
        return TargetActivity(callsign, TargetActivityKind.OTHER_QSO, "W1XYZ",
                              FT8MessageKind.REPORT, FT8Period(period), source)
    controller.observe_target_activity(activity("W2ZZZ", 102), FT8Period(103))
    controller.observe_target_activity(activity("K1ABC", 102, False), FT8Period(103))
    controller.observe_target_activity(activity("K1ABC", 98), FT8Period(103))
    for index in (101, 103, 105, 107, 109, 111):
        controller.on_period(FT8Period(index))
    controller.on_period(FT8Period(113))
    assert controller.state is FT8QsoState.RETRY_EXHAUSTED
    assert len(session.requests) == 6

    controller2, session2 = _started()
    controller2.observe_target_activity(activity("K1ABC", 102), FT8Period(103))
    controller2.on_period(FT8Period(101))
    controller2.on_decode(_decode(102, FT8MessageKind.REPORT))
    for index in (103, 105, 107, 109, 111, 113):
        controller2.on_period(FT8Period(index))
    controller2.on_period(FT8Period(115))
    assert controller2.state is FT8QsoState.RETRY_EXHAUSTED
    assert len(session2.requests) == 7  # 1 call + 6 post-transition R-reports.
    assert controller2.busy_extension_attempts == 0
