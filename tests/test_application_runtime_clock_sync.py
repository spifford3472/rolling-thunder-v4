"""Tests for GPS-assisted system-clock composition in the application runtime."""

from datetime import datetime
from pathlib import Path

import pytest

from rolling_thunder.application_runtime import ApplicationRuntime
from rolling_thunder.config import ApplicationConfig
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


class RecordingClockSetter:
    def __init__(self) -> None:
        self.values: list[datetime] = []

    def set_utc(self, value: datetime) -> None:
        self.values.append(value)


def real_gps_config() -> ApplicationConfig:
    return ApplicationConfig.model_validate(
        {
            "operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
            "hardware": {
                "mock": True,
                "radio_mode": "mock",
                "gps_mode": "real",
                "gps_device": "/dev/serial/by-id/gps",
            },
        }
    )


def mock_gps_config() -> ApplicationConfig:
    return ApplicationConfig.model_validate(
        {
            "operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
            "hardware": {"mock": True},
        }
    )


def gps_factory(
    _device: Path,
    *,
    baud_rate: int,
    timeout_s: float,
) -> MockGPSReceiver:
    assert baud_rate == 9_600
    assert timeout_s == 2.0
    return MockGPSReceiver()


def test_clock_sync_is_disabled_by_default_for_real_gps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ROLLING_THUNDER_GPS_CLOCK_SYNC", raising=False)

    runtime = ApplicationRuntime.from_config(
        real_gps_config(),
        gps_factory=gps_factory,
        scheduler=ManualScheduler(),
        gps_scheduler=ManualScheduler(),
    )

    assert runtime.clock_sync is None
    assert runtime.latest_clock_sync_state is None


def test_clock_sync_environment_flag_composes_real_gps_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ROLLING_THUNDER_GPS_CLOCK_SYNC", "1")
    clock_scheduler = ManualScheduler()
    setter = RecordingClockSetter()

    runtime = ApplicationRuntime.from_config(
        real_gps_config(),
        gps_factory=gps_factory,
        scheduler=ManualScheduler(),
        gps_scheduler=ManualScheduler(),
        clock_sync_scheduler=clock_scheduler,
        clock_sync_setter=setter,
    )

    assert runtime.clock_sync is not None
    assert runtime.latest_clock_sync_state is not None
    assert setter.values == []
    assert clock_scheduler.poll is None


def test_explicit_clock_sync_rejects_mock_gps() -> None:
    with pytest.raises(ValueError, match="requires real GPS hardware mode"):
        ApplicationRuntime.from_config(
            mock_gps_config(),
            scheduler=ManualScheduler(),
            gps_scheduler=ManualScheduler(),
            clock_sync_enabled=True,
            clock_sync_scheduler=ManualScheduler(),
            clock_sync_setter=RecordingClockSetter(),
        )


def test_clock_sync_lifecycle_runs_on_its_own_scheduler() -> None:
    radio_scheduler = ManualScheduler()
    gps_scheduler = ManualScheduler()
    clock_scheduler = ManualScheduler()
    setter = RecordingClockSetter()

    runtime = ApplicationRuntime.from_config(
        real_gps_config(),
        gps_factory=gps_factory,
        scheduler=radio_scheduler,
        gps_scheduler=gps_scheduler,
        clock_sync_scheduler=clock_scheduler,
        clock_sync_setter=setter,
        clock_sync_enabled=True,
    )

    runtime.start()

    assert runtime.clock_sync is not None
    assert runtime.clock_sync.is_running is True
    assert gps_scheduler.interval_s == 1.0
    assert clock_scheduler.interval_s == 1.0
    assert gps_scheduler.poll is not None
    assert clock_scheduler.poll is not None
    assert setter.values == []

    runtime.stop()

    assert runtime.clock_sync.is_running is False
    assert gps_scheduler.poll.cancelled is True
    assert clock_scheduler.poll.cancelled is True
    assert setter.values == []
