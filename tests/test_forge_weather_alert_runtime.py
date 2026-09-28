"""Runtime composition tests for optional Forge point-specific alerts."""

import logging
from collections.abc import Mapping
from pathlib import Path

import pytest

from rolling_thunder import forge_spot_main
from rolling_thunder.forge_config import ForgeApplicationConfig
from rolling_thunder.forge_spot_api import ForgeSpotApiApplication
from rolling_thunder.forge_spot_main import build_forge_runtime
from rolling_thunder.forge_weather_alerts import (
    ForgeWeatherAlertStorageError,
)
from rolling_thunder.http_home_platform import HttpResponse
from rolling_thunder.radio_polling import PollCallback


class ManualScheduledPoll:
    def __init__(self, callback: PollCallback) -> None:
        self.callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class RecordingScheduler:
    def __init__(self) -> None:
        self.intervals: list[float] = []
        self.polls: list[ManualScheduledPoll] = []

    def schedule_repeating(
        self,
        interval_s: float,
        callback: PollCallback,
    ) -> ManualScheduledPoll:
        self.intervals.append(interval_s)
        poll = ManualScheduledPoll(callback)
        self.polls.append(poll)
        return poll


class NoIoTransport:
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_s: float,
    ) -> HttpResponse:
        del method, url, headers, body, timeout_s
        raise AssertionError(
            "runtime composition must not perform provider HTTP"
        )


class FakeServer:
    def __init__(self) -> None:
        self.serve_count = 0
        self.shutdown_count = 0
        self.close_count = 0

    @property
    def server_address(self) -> tuple[str, int]:
        return "127.0.0.1", 8765

    def serve_forever(self) -> None:
        self.serve_count += 1

    def shutdown(self) -> None:
        self.shutdown_count += 1

    def close(self) -> None:
        self.close_count += 1


def config_for(
    tmp_path: Path,
    *,
    weather_alerts_enabled: bool = True,
) -> ForgeApplicationConfig:
    return ForgeApplicationConfig.model_validate(
        {
            "storage": {
                "database_path": tmp_path / "forge.db",
            },
            "aggregation": {
                "refresh_interval_s": 45,
                "refresh_on_start": False,
            },
            "pota": {
                "enabled": True,
            },
            "weather": {
                "enabled": False,
            },
            "weather_alerts": {
                "enabled": weather_alerts_enabled,
                "check_interval_s": 30,
                "location_max_age_s": 120,
                "refresh_on_start": False,
            },
            "radar": {
                "enabled": False,
            },
        }
    )


def test_enabled_weather_alerts_compose_without_http_and_follow_lifecycle(
    tmp_path: Path,
) -> None:
    spot_scheduler = RecordingScheduler()
    alert_scheduler = RecordingScheduler()
    server = FakeServer()
    captured: list[ForgeSpotApiApplication] = []

    def server_factory(
        host: str,
        port: int,
        application: ForgeSpotApiApplication,
    ) -> FakeServer:
        assert (host, port) == ("127.0.0.1", 8765)
        captured.append(application)
        return server

    runtime = build_forge_runtime(
        config_for(tmp_path),
        scheduler=spot_scheduler,
        weather_alert_scheduler=alert_scheduler,
        server_factory=server_factory,
        transport=NoIoTransport(),
        logger=logging.getLogger("test.forge.weather.alerts"),
    )

    assert runtime.weather_alerts is not None
    assert runtime.weather_alert_polling is not None
    assert spot_scheduler.intervals == []
    assert alert_scheduler.intervals == []

    runtime.run()

    assert spot_scheduler.intervals == [45]
    assert alert_scheduler.intervals == [30]

    assert spot_scheduler.polls[0].cancelled is True
    assert alert_scheduler.polls[0].cancelled is True

    assert server.serve_count == 1
    assert server.shutdown_count == 1
    assert server.close_count == 1

    response = captured[0].handle(
        "GET",
        "/api/v1/weather-alerts",
    )

    assert response.status_code == 200
    assert b'"status":"starting"' in response.body
    assert b'"applicability":"unavailable"' in response.body


def test_disabled_weather_alerts_leave_endpoint_unavailable(
    tmp_path: Path,
) -> None:
    captured: list[ForgeSpotApiApplication] = []

    def server_factory(
        host: str,
        port: int,
        application: ForgeSpotApiApplication,
    ) -> FakeServer:
        del host, port
        captured.append(application)
        return FakeServer()

    runtime = build_forge_runtime(
        config_for(
            tmp_path,
            weather_alerts_enabled=False,
        ),
        server_factory=server_factory,
    )

    assert runtime.weather_alerts is None
    assert runtime.weather_alert_polling is None

    response = captured[0].handle(
        "GET",
        "/api/v1/weather-alerts",
    )

    assert response.status_code == 503


def test_weather_alert_storage_failure_does_not_abort_core_forge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[ForgeSpotApiApplication] = []

    class FailingAlertRepository:
        def __init__(self, database_path: Path) -> None:
            del database_path
            raise ForgeWeatherAlertStorageError(
                "weather alert schema unavailable"
            )

    monkeypatch.setattr(
        forge_spot_main,
        "SqliteForgeWeatherAlertRepository",
        FailingAlertRepository,
    )

    def server_factory(
        host: str,
        port: int,
        application: ForgeSpotApiApplication,
    ) -> FakeServer:
        del host, port
        captured.append(application)
        return FakeServer()

    runtime = build_forge_runtime(
        config_for(tmp_path),
        server_factory=server_factory,
        logger=logging.getLogger(
            "test.forge.weather.alerts.failure"
        ),
    )

    assert runtime.weather_alerts is None
    assert runtime.weather_alert_polling is None

    response = captured[0].handle(
        "GET",
        "/api/v1/weather-alerts",
    )

    assert response.status_code == 503

    # Core Forge routes remain available.
    assert captured[0].handle(
        "GET",
        "/api/v1/health",
    ).status_code == 200
