"""Tests for configured POTA composition and application lifecycle wiring."""

from collections.abc import Mapping

import pytest
from pydantic import ValidationError

from rolling_thunder.application_runtime import ApplicationRuntime
from rolling_thunder.config import ApplicationConfig
from rolling_thunder.http_home_platform import UrllibHttpResponse
from rolling_thunder.pota_runtime import (
    PotaSpotsRuntimeConfig,
    build_pota_spot_polling,
)
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
    def __init__(self) -> None:
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
        return UrllibHttpResponse(200, b"[]")


def mock_application_config() -> ApplicationConfig:
    return ApplicationConfig.model_validate(
        {
            "operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
            "hardware": {"mock": True},
        }
    )


def test_disabled_pota_configuration_builds_no_service() -> None:
    polling = build_pota_spot_polling(
        PotaSpotsRuntimeConfig(),
        ManualScheduler(),
        mock_mode=True,
    )

    assert polling is None


def test_mock_runtime_starts_available_pota_polling_and_stops_cleanly() -> None:
    radio_scheduler = ManualScheduler()
    gps_scheduler = ManualScheduler()
    pota_scheduler = ManualScheduler()
    runtime = ApplicationRuntime.from_config(
        mock_application_config(),
        scheduler=radio_scheduler,
        gps_scheduler=gps_scheduler,
        pota_scheduler=pota_scheduler,
        pota_config=PotaSpotsRuntimeConfig(
            enabled=True,
            refresh_interval_s=45.0,
        ),
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
    assert state.spots == ()
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


def test_real_pota_composition_uses_configured_http_settings() -> None:
    scheduler = ManualScheduler()
    transport = RecordingTransport()
    polling = build_pota_spot_polling(
        PotaSpotsRuntimeConfig(
            enabled=True,
            base_url="https://spots.example.test/api",
            request_timeout_s=7.5,
            refresh_interval_s=90.0,
        ),
        scheduler,
        mock_mode=False,
        transport=transport,
    )
    assert polling is not None

    state = polling.start()

    assert state.availability is PotaSpotSourceAvailability.AVAILABLE
    assert transport.urls == ["https://spots.example.test/api/spot/activator"]
    assert transport.timeouts == [7.5]
    assert scheduler.interval_s == 90.0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("request_timeout_s", 0.0),
        ("refresh_interval_s", -1.0),
    ],
)
def test_pota_runtime_intervals_must_be_positive(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        PotaSpotsRuntimeConfig.model_validate({field: value})


def test_pota_runtime_settings_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        PotaSpotsRuntimeConfig.model_validate({"enabled": True, "token": "secret"})
