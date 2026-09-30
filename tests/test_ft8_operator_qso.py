"""Tests for the single-active-QSO operator service."""

from datetime import timedelta

import pytest

from rolling_thunder.ft8.activity import FT8CQActivityManager
from rolling_thunder.ft8.decoder import FT8PcmPeriod
from rolling_thunder.ft8.domain import FT8Period, FT8PeriodParity, FT8QsoContext, FT8QsoState
from rolling_thunder.ft8.operator_qso import FT8OperatorQsoService
from rolling_thunder.ft8.receive import FT8ReceiveService
from rolling_thunder.ft8.timing import FakeFT8Clock
from rolling_thunder.ft8.transmit import RecordingDigitalTransmitSession


class EmptyAudioInput:
    def start(self) -> None:
        return

    def read_period(self) -> FT8PcmPeriod:
        raise RuntimeError("not used")

    def stop(self) -> None:
        return


class EmptyDecoder:
    def decode(self, pcm: FT8PcmPeriod) -> tuple[()]:
        return ()


def _context(remote: str = "K1ABC") -> FT8QsoContext:
    period = FT8Period(100)
    return FT8QsoContext(
        local_callsign="KI5VNB",
        remote_callsign=remote,
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


def _receive() -> FT8ReceiveService:
    return FT8ReceiveService(
        EmptyAudioInput(),
        EmptyDecoder(),
        FT8CQActivityManager(),
    )


def test_operator_service_allows_only_one_authorized_qso() -> None:
    receive = _receive()
    sessions: list[RecordingDigitalTransmitSession] = []

    def factory(context: FT8QsoContext) -> RecordingDigitalTransmitSession:
        _ = context
        session = RecordingDigitalTransmitSession()
        sessions.append(session)
        return session

    context = _context()
    service = FT8OperatorQsoService(
        receive,
        factory,
        FakeFT8Clock(context.authorized_utc),
    )

    service.authorize_and_start(context)

    assert service.state is FT8QsoState.WAIT_TX_CALL
    assert service.context == context
    with pytest.raises(RuntimeError, match="already authorized"):
        service.authorize_and_start(_context("W1XYZ"))
    assert len(sessions) == 1

    service.abort()
    result = service.return_to_browser()

    assert result is not None
    assert result.status is FT8QsoState.ABORTED
    assert service.state is FT8QsoState.IDLE


def test_operator_service_refuses_browser_return_while_active() -> None:
    context = _context()
    service = FT8OperatorQsoService(
        _receive(),
        lambda _: RecordingDigitalTransmitSession(),
        FakeFT8Clock(context.authorized_utc),
    )
    service.authorize_and_start(context)

    with pytest.raises(RuntimeError, match="while a QSO is active"):
        service.return_to_browser()

    service.close()
    assert service.state is FT8QsoState.IDLE
