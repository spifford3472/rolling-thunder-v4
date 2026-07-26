"""Tests for the application composition root."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from rolling_thunder.application_runtime import ApplicationRuntime
from rolling_thunder.config import ApplicationConfig
from rolling_thunder.domain import GPSFixState, RadioConnectionState
from rolling_thunder.gps import GPSConnectionState, GPSReceiver
from rolling_thunder.mock_gps import MockGPSReceiver
from rolling_thunder.radio_polling import PollCallback
from rolling_thunder.serial_gps import SerialGPSReceiver


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
    radio_scheduler = ManualScheduler()
    gps_scheduler = ManualScheduler()
    runtime = ApplicationRuntime.from_config(
        mock_config(),
        scheduler=radio_scheduler,
        gps_scheduler=gps_scheduler,
    )

    state = runtime.start()

    assert state.connection_state is RadioConnectionState.CONNECTED
    assert runtime.latest_radio_state.connection_state is RadioConnectionState.CONNECTED
    assert isinstance(runtime.gps, MockGPSReceiver)
    assert runtime.gps_polling is not None
    assert runtime.gps_polling.is_running is True
    gps_state = runtime.latest_gps_state
    assert gps_state is not None
    assert gps_state.connection_state is GPSConnectionState.CONNECTED
    assert gps_state.position is not None
    assert gps_state.position.fix_state is GPSFixState.THREE_DIMENSIONAL
    assert radio_scheduler.poll is not None
    assert gps_scheduler.poll is not None


def test_runtime_stop_cancels_polling_and_disconnects_hardware() -> None:
    radio_scheduler = ManualScheduler()
    gps_scheduler = ManualScheduler()
    runtime = ApplicationRuntime.from_config(
        mock_config(),
        scheduler=radio_scheduler,
        gps_scheduler=gps_scheduler,
    )
    runtime.start()

    state = runtime.stop()

    assert state.connection_state is RadioConnectionState.DISCONNECTED
    gps_state = runtime.latest_gps_state
    assert gps_state is not None
    assert gps_state.connection_state is GPSConnectionState.DISCONNECTED
    assert gps_state.position is None
    assert radio_scheduler.poll is not None
    assert radio_scheduler.poll.cancelled is True
    assert gps_scheduler.poll is not None
    assert gps_scheduler.poll.cancelled is True
    assert runtime.gps is not None
    assert runtime.gps.get_state().connection_state is GPSConnectionState.DISCONNECTED


def test_non_mock_runtime_composes_serial_gps() -> None:
    runtime = ApplicationRuntime.from_config(
        hardware_config(),
        scheduler=ManualScheduler(),
        gps_scheduler=ManualScheduler(),
    )

    assert isinstance(runtime.gps, SerialGPSReceiver)
    assert runtime.gps_polling is not None
    gps_state = runtime.latest_gps_state
    assert gps_state is not None
    assert gps_state.connection_state is GPSConnectionState.DISCONNECTED


def test_non_mock_runtime_uses_configured_gps_device_with_injected_factory() -> None:
    received_devices: list[Path] = []
    receiver = MockGPSReceiver()

    def gps_factory(device: Path) -> GPSReceiver:
        received_devices.append(device)
        return receiver

    runtime = ApplicationRuntime.from_config(
        hardware_config(),
        scheduler=ManualScheduler(),
        gps_scheduler=ManualScheduler(),
        gps_factory=gps_factory,
    )

    assert received_devices == [Path("/dev/ttyUSB1")]
    assert runtime.gps is receiver
    assert runtime.latest_gps_state is receiver.get_state()


def test_runtime_rejects_repeated_start() -> None:
    runtime = ApplicationRuntime.from_config(
        mock_config(),
        scheduler=ManualScheduler(),
        gps_scheduler=ManualScheduler(),
    )
    runtime.start()

    with pytest.raises(RuntimeError, match="already started"):
        runtime.start()


def test_runtime_stop_before_start_is_safe() -> None:
    runtime = ApplicationRuntime.from_config(
        mock_config(),
        scheduler=ManualScheduler(),
        gps_scheduler=ManualScheduler(),
    )

    state = runtime.stop()

    assert state.connection_state is RadioConnectionState.DISCONNECTED
    gps_state = runtime.latest_gps_state
    assert gps_state is not None
    assert gps_state.connection_state is GPSConnectionState.DISCONNECTED


def test_test_clock_reference_is_timezone_aware() -> None:
    assert datetime(2026, 7, 25, tzinfo=UTC).utcoffset() is not None
