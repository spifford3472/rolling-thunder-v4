"""Tests for the application composition root."""

from datetime import UTC, datetime

import pytest

from rolling_thunder.application_runtime import ApplicationRuntime
from rolling_thunder.config import ApplicationConfig
from rolling_thunder.domain import GPSFixState, RadioConnectionState
from rolling_thunder.gps import GPSConnectionState
from rolling_thunder.mock_gps import MockGPSReceiver
from rolling_thunder.radio_polling import PollCallback


class ManualScheduledPoll:
    def __init__(self, callback: PollCallback) -> None:
        self.callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class ManualScheduler:
    def __init__(self) -> None:
        self.poll: ManualScheduledPoll | None = None

    def schedule_repeating(
        self,
        interval_s: float,
        callback: PollCallback,
    ) -> ManualScheduledPoll:
        assert interval_s == 1.0
        self.poll = ManualScheduledPoll(callback)
        return self.poll


def mock_config() -> ApplicationConfig:
    return ApplicationConfig.model_validate(
        {
            "operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
            "hardware": {"mock": True},
        }
    )


def hardware_config() -> ApplicationConfig:
    return ApplicationConfig.model_validate(
        {
            "operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
            "hardware": {
                "mock": False,
                "radio_device": "/dev/ttyUSB0",
                "gps_device": "/dev/ttyUSB1",
            },
        }
    )


def test_runtime_composes_and_starts_mock_hardware() -> None:
    scheduler = ManualScheduler()
    runtime = ApplicationRuntime.from_config(mock_config(), scheduler=scheduler)

    state = runtime.start()

    assert state.connection_state is RadioConnectionState.CONNECTED
    assert runtime.latest_radio_state.connection_state is RadioConnectionState.CONNECTED
    assert isinstance(runtime.gps, MockGPSReceiver)
    gps_state = runtime.latest_gps_state
    assert gps_state is not None
    assert gps_state.connection_state is GPSConnectionState.CONNECTED
    assert gps_state.position is not None
    assert gps_state.position.fix_state is GPSFixState.THREE_DIMENSIONAL
    assert scheduler.poll is not None


def test_runtime_stop_cancels_polling_and_disconnects_hardware() -> None:
    scheduler = ManualScheduler()
    runtime = ApplicationRuntime.from_config(mock_config(), scheduler=scheduler)
    runtime.start()

    state = runtime.stop()

    assert state.connection_state is RadioConnectionState.DISCONNECTED
    gps_state = runtime.latest_gps_state
    assert gps_state is not None
    assert gps_state.connection_state is GPSConnectionState.DISCONNECTED
    assert gps_state.position is None
    assert scheduler.poll is not None
    assert scheduler.poll.cancelled is True


def test_non_mock_runtime_leaves_gps_unconfigured() -> None:
    runtime = ApplicationRuntime.from_config(
        hardware_config(),
        scheduler=ManualScheduler(),
    )

    assert runtime.gps is None
    assert runtime.latest_gps_state is None


def test_runtime_rejects_repeated_start() -> None:
    runtime = ApplicationRuntime.from_config(
        mock_config(),
        scheduler=ManualScheduler(),
    )
    runtime.start()

    with pytest.raises(RuntimeError, match="already started"):
        runtime.start()


def test_runtime_stop_before_start_is_safe() -> None:
    runtime = ApplicationRuntime.from_config(
        mock_config(),
        scheduler=ManualScheduler(),
    )

    state = runtime.stop()

    assert state.connection_state is RadioConnectionState.DISCONNECTED
    gps_state = runtime.latest_gps_state
    assert gps_state is not None
    assert gps_state.connection_state is GPSConnectionState.DISCONNECTED


def test_test_clock_reference_is_timezone_aware() -> None:
    assert datetime(2026, 7, 25, tzinfo=UTC).utcoffset() is not None
