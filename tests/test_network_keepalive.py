"""Tests for cellular/WAN network keepalive behavior."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from rolling_thunder.application_runtime import ApplicationRuntime
from rolling_thunder.config import ApplicationConfig
from rolling_thunder.network_keepalive import (
    NetworkKeepaliveAvailability,
    NetworkKeepaliveService,
)
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


class RecordingTransport:
    def __init__(self) -> None:
        self.requests: list[tuple[str, float]] = []
        self.error: OSError | None = None

    def send(self, url: str, *, timeout_s: float) -> None:
        self.requests.append((url, timeout_s))
        if self.error is not None:
            raise self.error


def enabled_config() -> ApplicationConfig:
    return ApplicationConfig.model_validate(
        {
            "operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
            "hardware": {"mock": True},
            "network_keepalive": {
                "enabled": True,
                "target_url": "http://192.168.9.170:8080/health",
                "interval_s": 45,
                "timeout_s": 4,
            },
        }
    )


def test_keepalive_start_schedules_without_network_request() -> None:
    scheduler = ManualScheduler()
    transport = RecordingTransport()
    service = NetworkKeepaliveService(
        "https://example.test/health",
        scheduler,
        interval_s=30,
        timeout_s=5,
        transport=transport,
    )

    state = service.start()

    assert state.availability is NetworkKeepaliveAvailability.UNKNOWN
    assert transport.requests == []
    assert scheduler.interval_s == 30
    assert scheduler.poll is not None


def test_keepalive_callback_records_success() -> None:
    scheduler = ManualScheduler()
    transport = RecordingTransport()
    checked_at = datetime(2026, 7, 26, 21, 0, tzinfo=UTC)
    service = NetworkKeepaliveService(
        "https://example.test/health",
        scheduler,
        timeout_s=4,
        transport=transport,
        clock=lambda: checked_at,
    )
    service.start()
    assert scheduler.poll is not None

    scheduler.poll.callback()

    assert transport.requests == [("https://example.test/health", 4)]
    assert service.latest_state.availability is NetworkKeepaliveAvailability.REACHABLE
    assert service.latest_state.checked_at == checked_at
    assert service.latest_state.last_success_at == checked_at
    assert service.latest_state.last_error is None


def test_keepalive_failure_preserves_last_success() -> None:
    scheduler = ManualScheduler()
    transport = RecordingTransport()
    first = datetime(2026, 7, 26, 21, 0, tzinfo=UTC)
    current = [first]
    service = NetworkKeepaliveService(
        "https://example.test/health",
        scheduler,
        transport=transport,
        clock=lambda: current[0],
    )

    service.send_now()
    transport.error = OSError("cellular path unavailable")
    current[0] = first + timedelta(seconds=30)
    service.send_now()

    assert service.latest_state.availability is NetworkKeepaliveAvailability.UNREACHABLE
    assert service.latest_state.checked_at == current[0]
    assert service.latest_state.last_success_at == first
    assert service.latest_state.last_error == "cellular path unavailable"


def test_keepalive_stop_cancels_future_requests() -> None:
    scheduler = ManualScheduler()
    service = NetworkKeepaliveService(
        "https://example.test/health",
        scheduler,
        transport=RecordingTransport(),
    )
    service.start()
    assert scheduler.poll is not None

    service.stop()

    assert scheduler.poll.cancelled is True
    assert service.is_running is False


def test_keepalive_configuration_is_disabled_by_default() -> None:
    config = ApplicationConfig.model_validate(
        {"operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"}}
    )

    assert config.network_keepalive.enabled is False
    assert config.network_keepalive.target_url is None
    assert config.network_keepalive.interval_s == 30
    assert config.network_keepalive.timeout_s == 5


def test_enabled_keepalive_requires_target_url() -> None:
    with pytest.raises(ValidationError, match="network_keepalive.target_url"):
        ApplicationConfig.model_validate(
            {
                "operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
                "network_keepalive": {"enabled": True},
            }
        )


def test_runtime_composes_keepalive_without_startup_request() -> None:
    transport = RecordingTransport()
    keepalive_scheduler = ManualScheduler()
    runtime = ApplicationRuntime.from_config(
        enabled_config(),
        scheduler=ManualScheduler(),
        gps_scheduler=ManualScheduler(),
        network_keepalive_scheduler=keepalive_scheduler,
        network_keepalive_transport=transport,
    )

    assert runtime.network_keepalive is not None
    assert transport.requests == []

    runtime.start()

    assert transport.requests == []
    assert keepalive_scheduler.interval_s == 45
    assert keepalive_scheduler.poll is not None

    keepalive_scheduler.poll.callback()
    assert transport.requests == [("http://192.168.9.170:8080/health", 4)]

    runtime.stop()
    assert keepalive_scheduler.poll.cancelled is True


def test_disabled_runtime_does_not_compose_keepalive() -> None:
    config = ApplicationConfig.model_validate(
        {
            "operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
            "hardware": {"mock": True},
        }
    )

    runtime = ApplicationRuntime.from_config(
        config,
        scheduler=ManualScheduler(),
        gps_scheduler=ManualScheduler(),
    )

    assert runtime.network_keepalive is None
