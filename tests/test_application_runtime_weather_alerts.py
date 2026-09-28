"""ApplicationRuntime tests for location-aware Pi weather alerts."""

from concurrent.futures import Executor, Future
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rolling_thunder.application_runtime import (
    ApplicationRuntime,
)
from rolling_thunder.config import ApplicationConfig
from rolling_thunder.mock_gps import MockGPSReceiver
from rolling_thunder.pi_forge_weather_alert_service import (
    PiForgeWeatherAlertStateKind,
)
from rolling_thunder.radio_polling import PollCallback


class ImmediateExecutor(Executor):
    def submit(
        self,
        fn: Any,
        /,
        *args: Any,
        **kwargs: Any,
    ) -> Future[Any]:
        future: Future[Any] = Future()

        try:
            future.set_result(
                fn(*args, **kwargs)
            )
        except Exception as error:  # noqa: BLE001
            future.set_exception(error)

        return future

    def shutdown(
        self,
        wait: bool = True,
        *,
        cancel_futures: bool = False,
    ) -> None:
        del wait, cancel_futures


class ManualScheduledPoll:
    def __init__(
        self,
        callback: PollCallback,
    ) -> None:
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


def config(
    tmp_path: Path,
) -> ApplicationConfig:
    return ApplicationConfig.model_validate(
        {
            "operator": {
                "callsign": "KI5VNB",
                "home_grid": "EM79xm",
            },
            "hardware": {
                "mock": False,
                "radio_mode": "mock",
                "gps_mode": "real",
                "gps_device": "/dev/fake-gps",
            },
            "forge": {
                "enabled": True,
                "api_url": "http://forge.example.invalid",
                "refresh_on_start": False,
                "weather_alerts": {
                    "enabled": True,
                    "refresh_interval_s": 30.0,
                    "refresh_on_start": False,
                    "location_publish_interval_s": 15.0,
                },
            },
            "storage": {
                "database_path": str(
                    tmp_path / "rolling-thunder.db"
                )
            },
        }
    )


def test_runtime_owns_alert_and_fast_location_lifecycles(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 8, 9, 6, 50, tzinfo=UTC)

    radio_scheduler = ManualScheduler()
    gps_scheduler = ManualScheduler()
    forge_scheduler = ManualScheduler()
    alert_scheduler = ManualScheduler()
    location_scheduler = ManualScheduler()

    runtime = ApplicationRuntime.from_config(
        config(tmp_path),
        scheduler=radio_scheduler,
        gps_scheduler=gps_scheduler,
        forge_scheduler=forge_scheduler,
        forge_weather_alert_scheduler=alert_scheduler,
        forge_location_scheduler=location_scheduler,
        gps_factory=lambda *_args, **_kwargs: MockGPSReceiver(
            clock=lambda: now
        ),
        forge_location_executor_factory=ImmediateExecutor,
        forge_weather_alert_executor_factory=ImmediateExecutor,
    )

    alert_polling = runtime.pi_forge_weather_alert_polling
    location_publishing = runtime.pi_forge_location_publishing

    assert alert_polling is not None
    assert location_publishing is not None

    assert (
        runtime.latest_forge_weather_alert_state.kind
        is PiForgeWeatherAlertStateKind.NO_DATA
    )
    assert (
        runtime.latest_forge_weather_alert_notifications.sequence
        == 0
    )

    assert location_publishing.publish_interval_s == 15.0
    assert location_publishing.scheduler_interval_s == 5.0

    runtime.start()

    assert alert_polling.is_running is True
    assert alert_scheduler.interval_s == 30.0
    assert alert_scheduler.poll is not None

    assert location_publishing.is_running is True
    assert location_scheduler.interval_s == 5.0
    assert location_scheduler.poll is not None

    # Alert refresh-on-start is deliberately forbidden, so no
    # network request can race the initial location publication.
    assert alert_polling.refresh_count == 0

    runtime.stop()

    assert alert_polling.is_running is False
    assert alert_scheduler.poll.cancelled is True

    assert location_publishing.is_running is False
    assert location_scheduler.poll.cancelled is True
