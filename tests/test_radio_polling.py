"""Tests for deterministic automatic radio polling."""

from datetime import UTC, datetime

import pytest

from rolling_thunder.domain import (
    Frequency,
    RadioConnectionState,
    RadioMode,
    RadioState,
)
from rolling_thunder.radio import RadioBand, RadioConnectionError
from rolling_thunder.radio_polling import PollCallback, RadioPollingService

_DEFAULT_FREQUENCY = Frequency(hz=14_250_000)


class ManualScheduledPoll:
    def __init__(self, callback: PollCallback) -> None:
        self.callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True

    def fire(self) -> None:
        if not self.cancelled:
            self.callback()


class ManualScheduler:
    def __init__(self) -> None:
        self.interval_s: float | None = None
        self.poll: ManualScheduledPoll | None = None

    def schedule_repeating(
        self,
        interval_s: float,
        callback: PollCallback,
    ) -> ManualScheduledPoll:
        self.interval_s = interval_s
        self.poll = ManualScheduledPoll(callback)
        return self.poll

    def fire(self) -> None:
        assert self.poll is not None
        self.poll.fire()


class ScriptedRadio:
    def __init__(self) -> None:
        self.state = connected_state()
        self.refresh_count = 0
        self.next_refresh_state: RadioState | None = None
        self.refresh_error: RadioConnectionError | None = None
        self.during_refresh: PollCallback | None = None

    def connect(self) -> RadioState:
        return self.state

    def disconnect(self) -> RadioState:
        self.state = RadioState(
            connection_state=RadioConnectionState.DISCONNECTED,
            updated_at=timestamp(),
        )
        return self.state

    def get_state(self) -> RadioState:
        return self.state

    def refresh_state(self) -> RadioState:
        self.refresh_count += 1
        if self.during_refresh is not None:
            self.during_refresh()
        if self.refresh_error is not None:
            self.state = RadioState(
                connection_state=RadioConnectionState.ERROR,
                frequency=self.state.frequency,
                mode=self.state.mode,
                updated_at=timestamp(),
                last_error=str(self.refresh_error),
            )
            raise self.refresh_error
        if self.next_refresh_state is not None:
            self.state = self.next_refresh_state
        return self.state

    def set_frequency(self, frequency: Frequency) -> RadioState:
        self.state = connected_state(frequency=frequency, mode=self.state.mode)
        return self.state

    def set_mode(self, mode: RadioMode) -> RadioState:
        self.state = connected_state(frequency=self.state.frequency, mode=mode)
        return self.state

    def change_band(self, band: RadioBand) -> RadioState:
        del band
        return self.state


def timestamp() -> datetime:
    return datetime(2026, 7, 25, 6, 0, tzinfo=UTC)


def connected_state(
    *,
    frequency: Frequency | None = _DEFAULT_FREQUENCY,
    mode: RadioMode | None = RadioMode.USB,
) -> RadioState:
    return RadioState(
        connection_state=RadioConnectionState.CONNECTED,
        frequency=frequency,
        mode=mode,
        transmitting=False,
        updated_at=timestamp(),
    )


def test_start_schedules_configured_interval() -> None:
    radio = ScriptedRadio()
    scheduler = ManualScheduler()
    service = RadioPollingService(radio, scheduler, interval_s=0.5)

    state = service.start()

    assert state is radio.state
    assert service.is_running is True
    assert scheduler.interval_s == 0.5


def test_poll_publishes_manual_radio_change() -> None:
    radio = ScriptedRadio()
    scheduler = ManualScheduler()
    service = RadioPollingService(radio, scheduler)
    service.start()
    radio.next_refresh_state = connected_state(
        frequency=Frequency(hz=7_255_000),
        mode=RadioMode.LSB,
    )

    scheduler.fire()

    assert service.latest_state.frequency == Frequency(hz=7_255_000)
    assert service.latest_state.mode is RadioMode.LSB
    assert radio.refresh_count == 1
    assert service.is_running is True


def test_refresh_failure_stops_polling_and_publishes_error_state() -> None:
    radio = ScriptedRadio()
    scheduler = ManualScheduler()
    service = RadioPollingService(radio, scheduler)
    service.start()
    radio.refresh_error = RadioConnectionError("USB serial device disappeared")

    scheduler.fire()

    assert service.is_running is False
    assert scheduler.poll is not None
    assert scheduler.poll.cancelled is True
    assert service.latest_state.connection_state is RadioConnectionState.ERROR
    assert service.latest_state.last_error == "USB serial device disappeared"
    assert service.latest_state.frequency == Frequency(hz=14_250_000)


def test_stop_cancels_future_refreshes() -> None:
    radio = ScriptedRadio()
    scheduler = ManualScheduler()
    service = RadioPollingService(radio, scheduler)
    service.start()

    service.stop()
    scheduler.fire()

    assert service.is_running is False
    assert radio.refresh_count == 0


def test_repeated_start_is_rejected() -> None:
    service = RadioPollingService(ScriptedRadio(), ManualScheduler())
    service.start()

    with pytest.raises(RuntimeError, match="already running"):
        service.start()


def test_start_requires_connected_radio() -> None:
    radio = ScriptedRadio()
    radio.disconnect()
    service = RadioPollingService(radio, ManualScheduler())

    with pytest.raises(RadioConnectionError, match="requires a connected radio"):
        service.start()


def test_reentrant_callback_does_not_overlap_refresh() -> None:
    radio = ScriptedRadio()
    scheduler = ManualScheduler()
    service = RadioPollingService(radio, scheduler)
    service.start()
    radio.during_refresh = scheduler.fire

    scheduler.fire()

    assert radio.refresh_count == 1


@pytest.mark.parametrize("interval_s", [0.0, -1.0])
def test_polling_interval_must_be_positive(interval_s: float) -> None:
    with pytest.raises(ValueError, match="must be positive"):
        RadioPollingService(
            ScriptedRadio(),
            ManualScheduler(),
            interval_s=interval_s,
        )
