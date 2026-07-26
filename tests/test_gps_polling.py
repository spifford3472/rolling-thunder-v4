"""Tests for deterministic automatic GPS polling."""

from datetime import UTC, datetime

import pytest

from rolling_thunder.domain import GPSFixState, GPSPosition
from rolling_thunder.gps import (
    GPSConnectionState,
    GPSConnectionError,
    GPSError,
    GPSState,
)
from rolling_thunder.gps_polling import GPSPollingService
from rolling_thunder.radio_polling import PollCallback


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


class ScriptedGPSReceiver:
    def __init__(self) -> None:
        self.state = connected_state(latitude=39.75, longitude=-84.20)
        self.refresh_count = 0
        self.next_refresh_state: GPSState | None = None
        self.refresh_error: GPSError | None = None
        self.during_refresh: PollCallback | None = None

    def connect(self) -> GPSState:
        return self.state

    def disconnect(self) -> GPSState:
        self.state = disconnected_state()
        return self.state

    def get_state(self) -> GPSState:
        return self.state

    def refresh_state(self) -> GPSState:
        self.refresh_count += 1
        if self.during_refresh is not None:
            self.during_refresh()
        if self.refresh_error is not None:
            raise self.refresh_error
        if self.next_refresh_state is not None:
            self.state = self.next_refresh_state
        return self.state


def timestamp(minute: int = 0) -> datetime:
    return datetime(2026, 7, 26, 10, minute, tzinfo=UTC)


def disconnected_state() -> GPSState:
    return GPSState(
        connection_state=GPSConnectionState.DISCONNECTED,
        position=None,
        updated_at=timestamp(),
    )


def connected_state(*, latitude: float, longitude: float) -> GPSState:
    position = GPSPosition(
        fix_state=GPSFixState.THREE_DIMENSIONAL,
        latitude=latitude,
        longitude=longitude,
        altitude_m=250.0,
        satellites=8,
        updated_at=timestamp(),
    )
    return GPSState(
        connection_state=GPSConnectionState.CONNECTED,
        position=position,
        updated_at=position.updated_at,
    )


def test_start_schedules_configured_interval() -> None:
    gps = ScriptedGPSReceiver()
    scheduler = ManualScheduler()
    service = GPSPollingService(gps, scheduler, interval_s=0.5)

    state = service.start()

    assert state is gps.state
    assert service.is_running is True
    assert scheduler.interval_s == 0.5


def test_poll_publishes_new_position() -> None:
    gps = ScriptedGPSReceiver()
    scheduler = ManualScheduler()
    service = GPSPollingService(gps, scheduler)
    service.start()
    gps.next_refresh_state = connected_state(latitude=39.80, longitude=-84.10)

    scheduler.fire()

    assert service.latest_state.position is not None
    assert service.latest_state.position.latitude == 39.80
    assert service.latest_state.position.longitude == -84.10
    assert gps.refresh_count == 1
    assert service.is_running is True


def test_refresh_failure_publishes_error_and_keeps_polling() -> None:
    gps = ScriptedGPSReceiver()
    scheduler = ManualScheduler()
    service = GPSPollingService(gps, scheduler, clock=lambda: timestamp(1))
    service.start()
    gps.refresh_error = GPSConnectionError("NMEA sentence timed out")

    scheduler.fire()

    assert service.is_running is True
    assert scheduler.poll is not None
    assert scheduler.poll.cancelled is False
    assert service.latest_state.connection_state is GPSConnectionState.ERROR
    assert service.latest_state.last_error == "NMEA sentence timed out"
    assert service.latest_state.updated_at == timestamp(1)


def test_polling_recovers_after_transient_failure() -> None:
    gps = ScriptedGPSReceiver()
    scheduler = ManualScheduler()
    service = GPSPollingService(gps, scheduler, clock=lambda: timestamp(1))
    service.start()
    gps.refresh_error = GPSConnectionError("temporary read failure")
    scheduler.fire()
    gps.refresh_error = None
    gps.next_refresh_state = connected_state(latitude=39.90, longitude=-84.00)

    scheduler.fire()

    assert service.latest_state.connection_state is GPSConnectionState.CONNECTED
    assert service.latest_state.position is not None
    assert service.latest_state.position.latitude == 39.90
    assert service.is_running is True


def test_stop_cancels_future_refreshes() -> None:
    gps = ScriptedGPSReceiver()
    scheduler = ManualScheduler()
    service = GPSPollingService(gps, scheduler)
    service.start()

    service.stop()
    scheduler.fire()

    assert service.is_running is False
    assert gps.refresh_count == 0


def test_repeated_start_is_rejected() -> None:
    service = GPSPollingService(ScriptedGPSReceiver(), ManualScheduler())
    service.start()

    with pytest.raises(RuntimeError, match="already running"):
        service.start()


def test_start_requires_connected_receiver() -> None:
    gps = ScriptedGPSReceiver()
    gps.disconnect()
    service = GPSPollingService(gps, ManualScheduler())

    with pytest.raises(GPSError, match="requires a connected receiver"):
        service.start()


def test_reentrant_callback_does_not_overlap_refresh() -> None:
    gps = ScriptedGPSReceiver()
    scheduler = ManualScheduler()
    service = GPSPollingService(gps, scheduler)
    service.start()
    gps.during_refresh = scheduler.fire

    scheduler.fire()

    assert gps.refresh_count == 1


@pytest.mark.parametrize("interval_s", [0.0, -1.0])
def test_polling_interval_must_be_positive(interval_s: float) -> None:
    with pytest.raises(ValueError, match="must be positive"):
        GPSPollingService(
            ScriptedGPSReceiver(),
            ManualScheduler(),
            interval_s=interval_s,
        )
