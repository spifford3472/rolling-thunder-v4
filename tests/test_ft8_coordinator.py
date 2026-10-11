"""Deterministic tests for the Checkpoint 7 FT8 QSO coordinator."""

import threading
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from rolling_thunder.contact_logging import ContactLoggingService
from rolling_thunder.contact_repository import ContactRepository
from rolling_thunder.ft8.coordinator import FT8QsoCoordinator
from rolling_thunder.ft8.domain import (
    FT8Decode,
    FT8IncomingCall,
    FT8MessageKind,
    FT8Period,
    FT8PeriodParity,
    FT8QsoContext,
    FT8QsoState,
)
from rolling_thunder.ft8.logging import FT8QsoLoggingService
from rolling_thunder.ft8.timing import FakeFT8Clock
from rolling_thunder.ft8.transmit import FT8TransmitKind, RecordingDigitalTransmitSession


def _context() -> FT8QsoContext:
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
        authorized_utc=period.start_utc + timedelta(seconds=1),
        signal_report_db=-10,
    )


def _decode(
    period: int,
    kind: FT8MessageKind,
    *,
    source: str = "K1ABC",
) -> FT8Decode:
    return FT8Decode(
        period=FT8Period(period),
        snr_db=-8,
        dt_seconds=0.1,
        audio_frequency_hz=1500,
        raw_message=f"KI5VNB {source} {kind.value}",
        kind=kind,
        source_callsign=source,
        destination_callsign="KI5VNB",
        report_db=-8 if kind is FT8MessageKind.REPORT else None,
    )


def test_coordinator_drives_one_complete_qso_without_selecting_another_station() -> None:
    context = _context()
    clock = FakeFT8Clock(context.authorized_utc)
    session = RecordingDigitalTransmitSession()
    coordinator = FT8QsoCoordinator(session, clock)
    coordinator.authorize(context)
    coordinator.start_qso()

    clock.advance(14)
    coordinator.tick()
    assert session.requests[-1].kind is FT8TransmitKind.CALL

    clock.advance(15)
    coordinator.tick()
    coordinator.on_decodes((_decode(102, FT8MessageKind.REPORT),))

    clock.advance(15)
    coordinator.tick()
    assert session.requests[-1].kind is FT8TransmitKind.R_REPORT

    clock.advance(15)
    coordinator.tick()
    coordinator.on_decodes((_decode(104, FT8MessageKind.ACK_73),))

    clock.advance(15)
    coordinator.tick()

    assert coordinator.state is FT8QsoState.COMPLETED
    assert session.requests[-1].kind is FT8TransmitKind.SEVENTY_THREE
    assert coordinator.context == context


def test_terminal_handler_captures_final_ft8_power_before_exit_restore(
    tmp_path: Path,
) -> None:
    context = _context()
    clock = FakeFT8Clock(context.authorized_utc)
    session = RecordingDigitalTransmitSession()
    repository = ContactRepository(tmp_path / "contacts.db")
    logger = FT8QsoLoggingService(ContactLoggingService(repository))
    configured_power = {"watts": 55}
    lifecycle: list[tuple[str, int]] = []

    def handle_terminal(result):  # type: ignore[no-untyped-def]
        lifecycle.append(("terminal", configured_power["watts"]))
        return logger.handle_terminal_result(
            result,
            tx_power_watts=configured_power["watts"],
        )

    coordinator = FT8QsoCoordinator(
        session,
        clock,
        terminal_result_handler=handle_terminal,
    )
    coordinator.authorize(context)
    coordinator.start_qso()
    clock.advance(14)
    coordinator.tick()
    clock.advance(15)
    coordinator.tick()
    coordinator.on_decodes((_decode(102, FT8MessageKind.REPORT),))
    clock.advance(15)
    coordinator.tick()
    clock.advance(15)
    coordinator.tick()
    coordinator.on_decodes((_decode(104, FT8MessageKind.ACK_73),))
    clock.advance(15)
    coordinator.tick()

    configured_power["watts"] = 100
    lifecycle.append(("exit_restore", configured_power["watts"]))

    assert lifecycle == [("terminal", 55), ("exit_restore", 100)]
    assert repository.list_all()[0].tx_power_watts == 55


def test_responder_initial_report_is_retained_in_terminal_result() -> None:
    context = replace(
        _context(),
        remote_callsign="K0BQB",
        responder_inbound=FT8IncomingCall(
            callsign="K0BQB",
            period=FT8Period(100),
            snr_db=-3,
            dt_seconds=0.1,
            audio_frequency_hz=1500,
            kind=FT8MessageKind.REPORT,
            report_db=-3,
            raw_message="KI5VNB K0BQB -03",
        ),
    )
    clock = FakeFT8Clock(context.authorized_utc)
    session = RecordingDigitalTransmitSession()
    coordinator = FT8QsoCoordinator(session, clock)
    coordinator.authorize(context)
    coordinator.start_qso()

    clock.advance(14)
    coordinator.tick()
    assert session.requests[-1].kind is FT8TransmitKind.R_REPORT
    clock.advance(15)
    coordinator.tick()
    coordinator.on_decodes(
        (_decode(102, FT8MessageKind.ACK_73, source="K0BQB"),)
    )
    clock.advance(15)
    coordinator.tick()

    assert coordinator.result is not None
    assert coordinator.result.received_report_db == -3


def test_coordinator_fails_closed_on_receive_error() -> None:
    context = _context()
    session = RecordingDigitalTransmitSession()
    coordinator = FT8QsoCoordinator(session, FakeFT8Clock(context.authorized_utc))
    coordinator.authorize(context)
    coordinator.start_qso()

    coordinator.on_receive_error("decoder unavailable")

    assert coordinator.state is FT8QsoState.ERROR
    assert coordinator.terminal_reason == "FT8 receive failure: decoder unavailable"
    assert session.cancel_count == 1


def test_worker_processes_immediately_next_period_after_full_slot_transmit() -> None:
    context = _context()
    clock = FakeFT8Clock(context.authorized_utc)
    coordinator = FT8QsoCoordinator(RecordingDigitalTransmitSession(), clock)
    coordinator.authorize(context)
    coordinator.start_qso()

    # Model a physical transmit call returning 0.4 s after the next boundary.
    clock.advance(15.4)

    assert coordinator._next_worker_delay_s(clock.now_utc()) == 0.0

    coordinator.tick()

    assert coordinator.state is not FT8QsoState.ERROR
    assert coordinator.terminal_reason is None


def test_coordinator_fails_closed_when_utc_skips_a_period() -> None:
    context = _context()
    clock = FakeFT8Clock(context.authorized_utc)
    session = RecordingDigitalTransmitSession()
    coordinator = FT8QsoCoordinator(session, clock)
    coordinator.authorize(context)
    coordinator.start_qso()

    clock.advance(30)
    coordinator.tick()

    assert coordinator.state is FT8QsoState.ERROR
    assert coordinator.terminal_reason == "system UTC skipped an FT8 period"
    assert session.requests == []
    assert session.cancel_count == 1


def test_coordinator_abort_is_idempotent() -> None:
    context = _context()
    session = RecordingDigitalTransmitSession()
    coordinator = FT8QsoCoordinator(session, FakeFT8Clock(context.authorized_utc))
    coordinator.authorize(context)
    coordinator.start_qso()

    coordinator.abort()
    coordinator.abort()

    assert coordinator.state is FT8QsoState.ABORTED
    assert coordinator.terminal_reason == "operator abort"
    assert session.cancel_count == 1





class _CountingCancelSession:
    def __init__(self) -> None:
        self.cancel_count = 0

    def request(self, request: object) -> None:
        _ = request

    def cancel(self) -> None:
        self.cancel_count += 1


def test_coordinator_abort_calls_session_cancel_exactly_once() -> None:
    context = _context()
    session = _CountingCancelSession()
    coordinator = FT8QsoCoordinator(session, FakeFT8Clock(context.authorized_utc))
    coordinator.authorize(context)
    coordinator.start_qso()

    coordinator.abort()
    coordinator.abort()

    assert coordinator.state is FT8QsoState.ABORTED
    assert session.cancel_count == 1


def test_receive_error_calls_session_cancel_exactly_once() -> None:
    context = _context()
    session = _CountingCancelSession()
    coordinator = FT8QsoCoordinator(session, FakeFT8Clock(context.authorized_utc))
    coordinator.authorize(context)
    coordinator.start_qso()

    coordinator.on_receive_error("decoder unavailable")

    assert coordinator.state is FT8QsoState.ERROR
    assert session.cancel_count == 1


class _BlockingTransmitSession:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.cancelled = threading.Event()

    def request(self, request: object) -> None:
        _ = request
        self.entered.set()
        self.release.wait(2)

    def cancel(self) -> None:
        self.cancelled.set()


def test_abort_reaches_transmit_cancel_while_request_is_blocked() -> None:
    context = _context()
    clock = FakeFT8Clock(context.authorized_utc)
    session = _BlockingTransmitSession()
    coordinator = FT8QsoCoordinator(session, clock)
    coordinator.authorize(context)
    coordinator.start_qso()

    clock.advance(14)
    tick_thread = threading.Thread(target=coordinator.tick)
    tick_thread.start()
    assert session.entered.wait(1)

    abort_thread = threading.Thread(target=coordinator.abort)
    abort_thread.start()
    assert session.cancelled.wait(1)

    session.release.set()
    tick_thread.join(1)
    abort_thread.join(1)

    assert coordinator.state is FT8QsoState.ABORTED



def test_coordinator_fails_closed_when_utc_and_monotonic_diverge() -> None:
    context = _context()
    clock = FakeFT8Clock(context.authorized_utc)
    session = RecordingDigitalTransmitSession()
    coordinator = FT8QsoCoordinator(session, clock)
    coordinator.authorize(context)
    coordinator.start_qso()

    clock.advance_utc_only(15)
    coordinator.tick()

    assert coordinator.state is FT8QsoState.ERROR
    assert coordinator.terminal_reason == "system UTC and monotonic clocks diverged"
    assert session.requests == []
    assert session.cancel_count == 1


def test_cp31_integrated_coordinator_busy_target_periods_and_terminal_telemetry() -> None:
    from rolling_thunder.ft8.target_activity import FT8TargetActivityTracker

    context = _context()
    clock = FakeFT8Clock(context.authorized_utc)
    session = RecordingDigitalTransmitSession()
    tracker = FT8TargetActivityTracker(local_callsign=context.local_callsign)
    tracker.select(context.remote_callsign)
    activity = lambda: tracker.snapshot(clock.current_period())
    coordinator = FT8QsoCoordinator(session, clock, activity_provider=activity)
    coordinator.authorize(context)
    coordinator.start_qso()

    # Source-attributed third-party report arriving during our authorized session.
    other_reply = FT8Decode(
        period=FT8Period(102), snr_db=-7, dt_seconds=0.1, audio_frequency_hz=1500,
        raw_message="W1XYZ K1ABC -07", kind=FT8MessageKind.REPORT,
        source_callsign="K1ABC", destination_callsign="W1XYZ", report_db=-7,
    )
    for index in range(101, 118):
        clock.advance(15)
        if index == 102:
            tracker.observe((other_reply,), FT8Period(index))
            coordinator.on_decodes((other_reply,))  # Does not advance our phase.
        coordinator.tick()
    assert coordinator.state is FT8QsoState.RETRY_EXHAUSTED
    assert len(session.requests) == 8
    assert [r.attempt for r in session.requests] == list(range(1, 9))
    assert [r.busy_extension for r in session.requests] == [False] * 6 + [True] * 2
    assert coordinator.result is not None
    assert coordinator.result.busy_extension_attempts == 2
    assert coordinator.result.transmit_attempt_count == 8
    coordinator.reset()
    assert coordinator.state is FT8QsoState.IDLE


def test_cp31_ui_read_during_synchronous_transmit_never_waits_for_qso_slot() -> None:
    """UI needs to see TX state while the worker owns the tick lock."""
    entered = threading.Event()
    release = threading.Event()

    class BlockingSession(RecordingDigitalTransmitSession):
        def request(self, request: object) -> None:
            entered.set()
            assert release.wait(timeout=5)
            super().request(request)  # type: ignore[arg-type]

    context = _context()
    clock = FakeFT8Clock(context.authorized_utc)
    session = BlockingSession()
    coordinator = FT8QsoCoordinator(session, clock)
    coordinator.authorize(context)
    coordinator.start_qso()
    clock.advance(14)
    worker = threading.Thread(target=coordinator.tick)
    worker.start()
    assert entered.wait(timeout=2)
    observed: list[object] = []
    reader = threading.Thread(target=lambda: observed.append((
        coordinator.state, coordinator.context, coordinator.attempt_count,
        coordinator.attempts_per_state, coordinator.result,
    )))
    try:
        reader.start()
        reader.join(timeout=0.5)
        assert not reader.is_alive(), "UI read blocked for length of FT8 transmit"
        assert observed == [(FT8QsoState.TX_CALL, context, 1, 6, None)]
    finally:
        release.set()
        worker.join(timeout=3)
        reader.join(timeout=3)
    assert not worker.is_alive()
