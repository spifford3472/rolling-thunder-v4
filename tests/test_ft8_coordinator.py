"""Deterministic tests for the Checkpoint 7 FT8 QSO coordinator."""

import threading
from datetime import timedelta

from rolling_thunder.ft8.coordinator import FT8QsoCoordinator
from rolling_thunder.ft8.domain import (
    FT8Decode,
    FT8MessageKind,
    FT8Period,
    FT8PeriodParity,
    FT8QsoContext,
    FT8QsoState,
)
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


def _decode(period: int, kind: FT8MessageKind) -> FT8Decode:
    return FT8Decode(
        period=FT8Period(period),
        snr_db=-8,
        dt_seconds=0.1,
        audio_frequency_hz=1500,
        raw_message=f"KI5VNB K1ABC {kind.value}",
        kind=kind,
        source_callsign="K1ABC",
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
