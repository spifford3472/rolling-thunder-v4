"""Tests for Pi-side Forge shared-spot runtime composition."""

from pathlib import Path

from rolling_thunder.config import ForgeConfig
from rolling_thunder.pi_forge_runtime import build_pi_forge_spot_polling
from rolling_thunder.pi_forge_spot_service import PiForgeSpotStateKind
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


def test_disabled_forge_does_not_create_runtime_or_database(tmp_path: Path) -> None:
    database_path = tmp_path / "rolling-thunder.db"

    polling = build_pi_forge_spot_polling(
        ForgeConfig(),
        database_path=database_path,
        scheduler=ManualScheduler(),
    )

    assert polling is None
    assert database_path.exists() is False


def test_enabled_forge_builds_durable_polling_stack(tmp_path: Path) -> None:
    database_path = tmp_path / "rolling-thunder.db"
    scheduler = ManualScheduler()
    config = ForgeConfig.model_validate(
        {
            "enabled": True,
            "api_url": "https://forge.example.invalid/root",
            "refresh_interval_s": 45.0,
            "refresh_on_start": False,
        }
    )

    polling = build_pi_forge_spot_polling(
        config,
        database_path=database_path,
        scheduler=scheduler,
    )

    assert polling is not None
    assert database_path.is_file()
    assert polling.latest_state.kind is PiForgeSpotStateKind.EMPTY
    assert polling.latest_state.snapshot is None

    startup_state = polling.start()

    assert startup_state.kind is PiForgeSpotStateKind.EMPTY
    assert scheduler.interval_s == 45.0
    assert polling.is_running is True
    assert polling.is_refreshing is False

    stopped_state = polling.stop()

    assert stopped_state.kind is PiForgeSpotStateKind.EMPTY
    assert scheduler.poll is not None
    assert scheduler.poll.cancelled is True
    assert polling.is_running is False


def test_weather_alert_mode_caps_location_publication_cadence() -> None:
    from rolling_thunder.gps import GPSState
    from rolling_thunder.pi_forge_runtime import (
        build_pi_forge_location_publishing,
    )

    scheduler = ManualScheduler()
    config = ForgeConfig.model_validate(
        {
            "enabled": True,
            "api_url": "http://forge.example.invalid",
            "weather_alerts": {
                "enabled": True,
                "refresh_interval_s": 30.0,
                "location_publish_interval_s": 15.0,
            },
        }
    )

    publishing = build_pi_forge_location_publishing(
        config,
        lambda: GPSState(),
        scheduler=scheduler,
    )

    assert publishing is not None

    # Normal retained-location defaults are 600/60/30/30 seconds.
    # Alert mode must cap them to current-location-safe values.
    assert publishing.publish_interval_s == 15.0
    assert publishing.retry_interval_s == 15.0
    assert publishing.unusable_retry_interval_s == 5.0
    assert publishing.scheduler_interval_s == 5.0


def test_normal_forge_location_keeps_existing_ten_minute_cadence() -> None:
    from rolling_thunder.gps import GPSState
    from rolling_thunder.pi_forge_runtime import (
        build_pi_forge_location_publishing,
    )

    config = ForgeConfig.model_validate(
        {
            "enabled": True,
            "api_url": "http://forge.example.invalid",
        }
    )

    publishing = build_pi_forge_location_publishing(
        config,
        lambda: GPSState(),
        scheduler=ManualScheduler(),
    )

    assert publishing is not None
    assert publishing.publish_interval_s == 600.0
    assert publishing.retry_interval_s == 60.0
    assert publishing.unusable_retry_interval_s == 30.0
    assert publishing.scheduler_interval_s == 30.0


def test_enabled_alerts_build_independent_retained_polling_stack(
    tmp_path: Path,
) -> None:
    from datetime import UTC, datetime

    from rolling_thunder.domain import (
        GPSFixState,
        GPSPosition,
    )
    from rolling_thunder.gps import (
        GPSConnectionState,
        GPSState,
        GPSUTCObservation,
        GPSUTCSource,
    )
    from rolling_thunder.pi_forge_runtime import (
        build_pi_forge_weather_alert_polling,
    )
    from rolling_thunder.pi_forge_weather_alert_service import (
        PiForgeWeatherAlertStateKind,
    )

    now = datetime(2026, 8, 9, 6, 45, tzinfo=UTC)

    gps = GPSState(
        connection_state=GPSConnectionState.CONNECTED,
        position=GPSPosition(
            fix_state=GPSFixState.THREE_DIMENSIONAL,
            latitude=39.5245,
            longitude=-84.0625,
            speed_m_s=0.0,
            accuracy_m=3.0,
            updated_at=now,
        ),
        updated_at=now,
        utc=GPSUTCObservation(
            value=now,
            source=GPSUTCSource.RMC,
            valid=True,
            fix_valid=True,
            advancing=True,
            fresh=True,
            age_s=0.0,
            received_monotonic_s=100.0,
        ),
    )

    scheduler = ManualScheduler()

    config = ForgeConfig.model_validate(
        {
            "enabled": True,
            "api_url": "http://forge.example.invalid",
            "weather_alerts": {
                "enabled": True,
                "refresh_interval_s": 30.0,
                "refresh_on_start": False,
                "location_publish_interval_s": 15.0,
            },
        }
    )

    polling = build_pi_forge_weather_alert_polling(
        config,
        lambda: gps,
        database_path=tmp_path / "rolling-thunder.db",
        scheduler=scheduler,
        clock=lambda: now,
        monotonic_clock=lambda: 102.0,
    )

    assert polling is not None
    assert (
        polling.latest_state.kind
        is PiForgeWeatherAlertStateKind.NO_DATA
    )
    assert polling.latest_notification_batch.sequence == 0

    polling.start()

    assert scheduler.interval_s == 30.0
    assert scheduler.poll is not None
    assert polling.is_running is True
    assert polling.is_refreshing is False

    polling.stop()

    assert scheduler.poll.cancelled is True
    assert polling.is_running is False
