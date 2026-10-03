"""Tests for background FT8 QSO preparation/start and exit restore."""

from datetime import UTC, datetime

from rolling_thunder.domain import Frequency, RadioConnectionState, RadioMode, RadioState
from rolling_thunder.ft8.domain import FT8CQActivity, FT8Period
from rolling_thunder.ft8.radio_preparation import (
    FT8RadioPreparationError,
    FT8RadioPreparationService,
)
from rolling_thunder.ft8.start_control import FT8QsoStartController, FT8QsoStartState
from rolling_thunder.ft891_cat import Ft891SsbBfo


def _activity() -> FT8CQActivity:
    return FT8CQActivity(
        callsign="K1ABC",
        last_period=FT8Period(100),
        snr_db=-8,
        dt_seconds=0.1,
        audio_frequency_hz=1500,
        grid="FN31",
    )


def _state(frequency_hz: int = 14_250_000) -> RadioState:
    return RadioState(
        connection_state=RadioConnectionState.CONNECTED,
        frequency=Frequency(hz=frequency_hz),
        mode=RadioMode.DATA,
        transmitting=False,
        updated_at=datetime(2026, 10, 2, 20, 0, tzinfo=UTC),
    )


class Radio:
    def __init__(self) -> None:
        self.state = _state()
        self.power_watts = 100
        self.ssb_bfo = Ft891SsbBfo.AUTO
        self.fail_bfo = False
        self.calls: list[str] = []

    def refresh_state(self) -> RadioState:
        self.calls.append("refresh")
        return self.state

    def set_frequency(self, frequency: Frequency) -> RadioState:
        self.calls.append(f"frequency:{frequency.hz}")
        self.state = _state(frequency.hz)
        return self.state

    def set_power_watts(self, power_watts: int) -> int:
        self.calls.append(f"power:{power_watts}")
        self.power_watts = power_watts
        return power_watts

    def set_ssb_bfo(self, value: Ft891SsbBfo) -> Ft891SsbBfo:
        self.calls.append(f"bfo:{value.value}")
        if self.fail_bfo and value is Ft891SsbBfo.USB:
            raise FT8RadioPreparationError("USB BFO unavailable")
        self.ssb_bfo = value
        return value


def _run_now(worker: object) -> None:
    assert callable(worker)
    worker()


def test_successful_prepare_starts_existing_qso_path_only_after_verification() -> None:
    radio = Radio()
    starts: list[tuple[str, int]] = []
    controller = FT8QsoStartController(
        FT8RadioPreparationService(radio),
        lambda activity, state: starts.append(
            (activity.callsign, state.frequency.hz if state.frequency else 0)
        ),
        worker_launcher=_run_now,
    )

    assert controller.start(_activity()) is True

    assert starts == [("K1ABC", 14_074_000)]
    assert controller.status.state is FT8QsoStartState.STARTED
    assert radio.power_watts == 20
    assert radio.ssb_bfo is Ft891SsbBfo.USB


def test_prepare_failure_never_calls_qso_starter_and_rolls_back() -> None:
    radio = Radio()
    radio.fail_bfo = True
    starts: list[str] = []
    controller = FT8QsoStartController(
        FT8RadioPreparationService(radio),
        lambda activity, state: starts.append(activity.callsign),
        worker_launcher=_run_now,
    )

    assert controller.start(_activity()) is True

    assert starts == []
    assert controller.status.state is FT8QsoStartState.FAILED
    assert controller.status.error is not None
    assert "USB BFO unavailable" in controller.status.error
    assert radio.power_watts == 100
    assert radio.ssb_bfo is Ft891SsbBfo.AUTO


def test_exit_requested_during_preparation_skips_qso_start_and_restores() -> None:
    radio = Radio()
    starts: list[str] = []
    queued: list[object] = []
    controller = FT8QsoStartController(
        FT8RadioPreparationService(radio),
        lambda activity, state: starts.append(activity.callsign),
        worker_launcher=queued.append,
    )

    assert controller.start(_activity()) is True
    assert controller.status.state is FT8QsoStartState.PREPARING
    assert controller.request_restore() is True

    worker = queued.pop(0)
    assert callable(worker)
    worker()

    assert starts == []
    assert controller.status.state is FT8QsoStartState.RESTORED
    assert radio.power_watts == 100
    assert radio.ssb_bfo is Ft891SsbBfo.AUTO


def test_explicit_exit_restore_is_background_and_idempotent_while_running() -> None:
    radio = Radio()
    queued: list[object] = []
    controller = FT8QsoStartController(
        FT8RadioPreparationService(radio),
        lambda activity, state: None,
        worker_launcher=queued.append,
    )

    assert controller.request_restore() is True
    assert controller.status.state is FT8QsoStartState.RESTORING
    assert controller.request_restore() is False

    worker = queued.pop(0)
    assert callable(worker)
    worker()

    assert controller.status.state is FT8QsoStartState.RESTORED
    assert radio.power_watts == 100
    assert radio.ssb_bfo is Ft891SsbBfo.AUTO


def test_qso_start_error_is_published_without_transmit_retry() -> None:
    radio = Radio()

    def fail_start(activity: FT8CQActivity, state: RadioState) -> None:
        del activity, state
        raise RuntimeError("selected CQ expired")

    controller = FT8QsoStartController(
        FT8RadioPreparationService(radio),
        fail_start,
        worker_launcher=_run_now,
    )

    assert controller.start(_activity()) is True

    assert controller.status.state is FT8QsoStartState.FAILED
    assert controller.status.error == "selected CQ expired"
