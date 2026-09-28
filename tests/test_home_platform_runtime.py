"""Tests for Home Station Platform runtime composition."""

from collections.abc import Mapping
from pathlib import Path

from rolling_thunder.application_runtime import ApplicationRuntime
from rolling_thunder.config import ApplicationConfig
from rolling_thunder.home_platform_health import HomePlatformHealthService
from rolling_thunder.http_home_platform import (
    HttpHomePlatformClient,
    HttpResponse,
)
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


class FakeResponse:
    def __init__(self, status_code: int, body: bytes) -> None:
        self._status_code = status_code
        self._body = body

    @property
    def status_code(self) -> int:
        return self._status_code

    @property
    def body(self) -> bytes:
        return self._body


class RecordingTransport:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, float]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_s: float,
    ) -> HttpResponse:
        del headers, body
        self.requests.append((method, url, timeout_s))
        return FakeResponse(
            200,
            b'{"availability":"available","checked_at":"2026-07-26T21:00:00Z"}',
        )


def runtime_config(tmp_path: Path, *, enabled: bool) -> ApplicationConfig:
    home_platform: dict[str, object] = {"enabled": False}
    if enabled:
        home_platform = {
            "enabled": True,
            "base_url": "https://forge.example.invalid/platform",
            "request_timeout_s": 3.5,
            "health_poll_interval_s": 12,
            "contact_sync_interval_s": 17,
            "contact_sync_batch_size": 40,
        }
    return ApplicationConfig.model_validate(
        {
            "operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
            "hardware": {"mock": True},
            "home_platform": home_platform,
            "storage": {"database_path": tmp_path / "runtime.db"},
        }
    )


def test_disabled_platform_composes_no_services_or_network_activity(tmp_path: Path) -> None:
    """The default-disabled platform must leave the runtime fully offline."""
    radio_scheduler = RecordingScheduler()
    gps_scheduler = RecordingScheduler()
    health_scheduler = RecordingScheduler()
    sync_scheduler = RecordingScheduler()
    transport = RecordingTransport()

    runtime = ApplicationRuntime.from_config(
        runtime_config(tmp_path, enabled=False),
        scheduler=radio_scheduler,
        gps_scheduler=gps_scheduler,
        home_platform_scheduler=health_scheduler,
        contact_sync_scheduler=sync_scheduler,
        home_platform_transport=transport,
    )

    assert runtime.home_platform_client is None
    assert runtime.home_platform_health is None
    assert runtime.contact_sync is None

    runtime.start()

    assert health_scheduler.intervals == []
    assert sync_scheduler.intervals == []
    assert transport.requests == []
    runtime.stop()


def test_enabled_platform_composes_and_starts_configured_services(tmp_path: Path) -> None:
    """Enabled settings should create and schedule both platform services."""
    health_scheduler = RecordingScheduler()
    sync_scheduler = RecordingScheduler()
    transport = RecordingTransport()
    runtime = ApplicationRuntime.from_config(
        runtime_config(tmp_path, enabled=True),
        scheduler=RecordingScheduler(),
        gps_scheduler=RecordingScheduler(),
        home_platform_scheduler=health_scheduler,
        contact_sync_scheduler=sync_scheduler,
        home_platform_transport=transport,
    )

    assert isinstance(runtime.home_platform_client, HttpHomePlatformClient)
    assert isinstance(runtime.home_platform_health, HomePlatformHealthService)
    assert runtime.contact_sync is not None
    assert transport.requests == []
    assert health_scheduler.intervals == []
    assert sync_scheduler.intervals == []

    runtime.start()

    assert health_scheduler.intervals == [12]
    assert sync_scheduler.intervals == [17]
    assert runtime.home_platform_health.is_running is True
    assert runtime.contact_sync.is_running is True
    assert transport.requests == []


def test_health_poll_uses_configured_url_and_timeout(tmp_path: Path) -> None:
    """The composed HTTP client should receive endpoint and timeout settings."""
    health_scheduler = RecordingScheduler()
    transport = RecordingTransport()
    runtime = ApplicationRuntime.from_config(
        runtime_config(tmp_path, enabled=True),
        scheduler=RecordingScheduler(),
        gps_scheduler=RecordingScheduler(),
        home_platform_scheduler=health_scheduler,
        contact_sync_scheduler=RecordingScheduler(),
        home_platform_transport=transport,
    )
    runtime.start()

    health_scheduler.polls[0].callback()

    assert transport.requests == [
        ("GET", "https://forge.example.invalid/platform/health", 3.5)
    ]
    runtime.stop()


def test_runtime_stop_cancels_platform_services(tmp_path: Path) -> None:
    """Runtime shutdown should stop future health and synchronization work."""
    health_scheduler = RecordingScheduler()
    sync_scheduler = RecordingScheduler()
    runtime = ApplicationRuntime.from_config(
        runtime_config(tmp_path, enabled=True),
        scheduler=RecordingScheduler(),
        gps_scheduler=RecordingScheduler(),
        home_platform_scheduler=health_scheduler,
        contact_sync_scheduler=sync_scheduler,
        home_platform_transport=RecordingTransport(),
    )
    runtime.start()

    runtime.stop()

    assert health_scheduler.polls[0].cancelled is True
    assert sync_scheduler.polls[0].cancelled is True
    assert runtime.home_platform_health is not None
    assert runtime.home_platform_health.is_running is False
    assert runtime.contact_sync is not None
    assert runtime.contact_sync.is_running is False
