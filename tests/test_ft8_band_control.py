"""Tests for background FT8 band cycling through receive tuning."""

from datetime import UTC, datetime
from threading import Event

from rolling_thunder.domain import Frequency, RadioConnectionState, RadioMode, RadioState
from rolling_thunder.ft8.band_control import FT8BandController, FT8BandTuneState
from rolling_thunder.radio import RadioBand, RadioConnectionError
from rolling_thunder.receive_tuning import ReceiveTuneOutcome


def _state(frequency_hz: int = 14_074_000) -> RadioState:
    return RadioState(
        connection_state=RadioConnectionState.CONNECTED,
        frequency=Frequency(hz=frequency_hz),
        mode=RadioMode.DATA,
        transmitting=False,
        updated_at=datetime(2026, 10, 2, 20, 0, tzinfo=UTC),
    )


class Tuner:
    def __init__(self) -> None:
        self.calls: list[tuple[Frequency, RadioMode]] = []
        self.error: Exception | None = None
        self.called = Event()

    def tune(self, frequency: Frequency, mode: RadioMode) -> ReceiveTuneOutcome:
        self.calls.append((frequency, mode))
        self.called.set()
        if self.error is not None:
            raise self.error
        return ReceiveTuneOutcome(
            state=_state(frequency.hz),
            target_band=RadioBand.BAND_17M,
            band_changed=True,
        )


def test_cycle_band_moves_20m_to_17m_ft8_frequency() -> None:
    tuner = Tuner()
    controller = FT8BandController(tuner, lambda: _state())

    assert controller.cycle_band() is True
    assert tuner.called.wait(timeout=1.0)

    assert tuner.calls == [(Frequency(hz=18_100_000), RadioMode.DATA)]
    assert controller.status.state is FT8BandTuneState.SUCCEEDED
    assert controller.status.target_band is RadioBand.BAND_17M
    assert controller.status.outcome is not None
    assert controller.status.outcome.band_changed is True


def test_cycle_from_60m_falls_back_to_20m_automated_band() -> None:
    tuner = Tuner()
    controller = FT8BandController(tuner, lambda: _state(5_357_000))

    assert controller.cycle_band() is True
    assert tuner.called.wait(timeout=1.0)

    assert tuner.calls == [(Frequency(hz=14_074_000), RadioMode.DATA)]


def test_band_tune_failure_is_published_without_retry() -> None:
    tuner = Tuner()
    tuner.error = RadioConnectionError("radio unavailable")
    controller = FT8BandController(tuner, lambda: _state())

    assert controller.cycle_band() is True
    assert tuner.called.wait(timeout=1.0)

    assert controller.status.state is FT8BandTuneState.FAILED
    assert controller.status.error == "radio unavailable"
