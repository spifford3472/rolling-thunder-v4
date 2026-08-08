"""Tests for configured POTA composition and application lifecycle wiring."""

from collections.abc import Mapping
from json import dumps
from pathlib import Path

from rolling_thunder.application_runtime import ApplicationRuntime
from rolling_thunder.config import ApplicationConfig, PotaSpotsConfig
from rolling_thunder.http_home_platform import UrllibHttpResponse
from rolling_thunder.pota_runtime import build_pota_spot_polling
from rolling_thunder.pota_spot_source import PotaSpotSourceAvailability
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
    def __init__(self, body: bytes = b"[]") -> None:
        self.body = body
        self.urls: list[str] = []
        self.timeouts: list[float] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_s: float,
    ) -> UrllibHttpResponse:
        assert method == "GET"
        assert headers == {"Accept": "application/json"}
        assert body is None
        self.urls.append(url)
        self.timeouts.append(timeout_s)
        return UrllibHttpResponse(200, self.body)


def live_spot_payload() -> bytes:
    return dumps(
        [
            {
                "activator": "KI5VNB/P",
                "frequency": "14250.0",
                "mode": "SSB",
                "reference": "US-1234",
                "spotTime": "2026-08-01T23:00:00Z",
                "comments": "Strong signal",
                "name": "Caesar Creek State Park",
                "parkName": None,
            }
        ]
    ).encode("utf-8")


def mock_application_config(
    *,
    database_path: Path | None = None,
    pota_enabled: bool = False,
    forge_enabled: bool = False,
) -> ApplicationConfig:
    values: dict[str, object] = {
        "operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
        "hardware": {"mock": True},
        "forge": {
            "enabled": forge_enabled,
            "api_url": (
                "http://forge.example.test:8766"
                if forge_enabled
                else None
            ),
        },
        "pota_spots": {
            "enabled": pota_enabled,
            "refresh_interval_s": 45.0,
        },
    }

    if database_path is not None:
        values["storage"] = {"database_path": database_path}

    return ApplicationConfig.model_validate(values)


def test_disabled_pota_configuration_builds_no_service(tmp_path: Path) -> None:
    polling = build_pota_spot_polling(
        PotaSpotsConfig(),
        ManualScheduler(),
        database_path=tmp_path / "contacts.sqlite3",
        mock_mode=True,
    )

    assert polling is None


def test_mock_hardware_runtime_still_uses_live_pota_http_source(
    tmp_path: Path,
) -> None:
    radio_scheduler = ManualScheduler()
    gps_scheduler = ManualScheduler()
    pota_scheduler = ManualScheduler()
    transport = RecordingTransport(live_spot_payload())
    runtime = ApplicationRuntime.from_config(
        mock_application_config(
            database_path=tmp_path / "contacts.sqlite3",
            pota_enabled=True,
        ),
        scheduler=radio_scheduler,
        gps_scheduler=gps_scheduler,
        pota_scheduler=pota_scheduler,
        pota_transport=transport,
    )

    assert runtime.latest_pota_spot_state is not None
    assert (
        runtime.latest_pota_spot_state.availability
        is PotaSpotSourceAvailability.UNKNOWN
    )

    runtime.start()

    state = runtime.latest_pota_spot_state
    assert state is not None
    assert state.availability is PotaSpotSourceAvailability.AVAILABLE
    assert len(state.spots) == 1
    assert str(state.spots[0].activator) == "KI5VNB/P"
    assert transport.urls == ["https://api.pota.app/spot/activator"]
    assert runtime.pota_spot_polling is not None
    assert runtime.pota_spot_polling.is_running is True
    assert runtime.pota_spot_polling.refresh_count == 1
    assert pota_scheduler.interval_s == 45.0

    runtime.stop()

    assert runtime.pota_spot_polling.is_running is False
    assert pota_scheduler.poll is not None
    assert pota_scheduler.poll.cancelled is True


def test_runtime_leaves_pota_state_absent_when_disabled() -> None:
    runtime = ApplicationRuntime.from_config(
        mock_application_config(),
        scheduler=ManualScheduler(),
        gps_scheduler=ManualScheduler(),
    )

    assert runtime.pota_spot_polling is None
    assert runtime.latest_pota_spot_state is None


def test_forge_enabled_runtime_does_not_build_legacy_pota_poller(
    tmp_path: Path,
) -> None:
    transport = RecordingTransport(live_spot_payload())

    runtime = ApplicationRuntime.from_config(
        mock_application_config(
            database_path=tmp_path / "contacts.sqlite3",
            pota_enabled=True,
            forge_enabled=True,
        ),
        scheduler=ManualScheduler(),
        gps_scheduler=ManualScheduler(),
        pota_scheduler=ManualScheduler(),
        pota_transport=transport,
    )

    assert runtime.pi_forge_spot_polling is not None
    assert runtime.pota_spot_polling is None
    assert runtime.latest_pota_spot_state is None
    assert transport.urls == []


def test_real_pota_composition_uses_configured_http_settings(tmp_path: Path) -> None:
    scheduler = ManualScheduler()
    transport = RecordingTransport()
    polling = build_pota_spot_polling(
        PotaSpotsConfig(
            enabled=True,
            base_url="https://spots.example.test/api",
            request_timeout_s=7.5,
            refresh_interval_s=90.0,
        ),
        scheduler,
        database_path=tmp_path / "contacts.sqlite3",
        mock_mode=False,
        transport=transport,
    )
    assert polling is not None

    state = polling.start()

    assert state.availability is PotaSpotSourceAvailability.AVAILABLE
    assert transport.urls == ["https://spots.example.test/api/spot/activator"]
    assert transport.timeouts == [7.5]
    assert scheduler.interval_s == 90.0


def test_new_runtime_loads_previous_successful_snapshot_as_stale(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "contacts.sqlite3"
    first_transport = RecordingTransport(live_spot_payload())

    first_runtime = ApplicationRuntime.from_config(
        mock_application_config(
            database_path=database_path,
            pota_enabled=True,
        ),
        scheduler=ManualScheduler(),
        gps_scheduler=ManualScheduler(),
        pota_scheduler=ManualScheduler(),
        pota_transport=first_transport,
    )

    first_runtime.start()

    first_state = first_runtime.latest_pota_spot_state
    assert first_state is not None
    assert first_state.availability is PotaSpotSourceAvailability.AVAILABLE
    assert first_state.last_success_at is not None
    assert len(first_state.spots) == 1

    first_runtime.stop()

    second_transport = RecordingTransport(live_spot_payload())
    second_runtime = ApplicationRuntime.from_config(
        mock_application_config(
            database_path=database_path,
            pota_enabled=True,
        ),
        scheduler=ManualScheduler(),
        gps_scheduler=ManualScheduler(),
        pota_scheduler=ManualScheduler(),
        pota_transport=second_transport,
    )

    cached_state = second_runtime.latest_pota_spot_state

    assert cached_state is not None
    assert cached_state.availability is PotaSpotSourceAvailability.UNAVAILABLE
    assert cached_state.spots == first_state.spots
    assert cached_state.last_success_at == first_state.last_success_at
    assert cached_state.is_stale is True
    assert cached_state.last_error == (
        "Using cached POTA spots until a live refresh succeeds."
    )

    second_runtime.start()

    refreshed_state = second_runtime.latest_pota_spot_state
    assert refreshed_state is not None
    assert refreshed_state.availability is PotaSpotSourceAvailability.AVAILABLE
    assert refreshed_state.is_stale is False
    assert len(refreshed_state.spots) == 1

    second_runtime.stop()
