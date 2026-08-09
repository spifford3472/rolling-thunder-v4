"""Tests for the Pi retained Forge weather-alert HTTP client."""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from json import dumps

import pytest

from rolling_thunder.forge_weather_alert_client import (
    ForgeWeatherAlertClientTransportError,
    ForgeWeatherAlertClientValidationError,
    HttpForgeWeatherAlertClient,
)
from rolling_thunder.forge_weather_alerts import (
    WeatherAlertApplicability,
    WeatherAlertCertainty,
    WeatherAlertProviderStatus,
    WeatherAlertRecord,
    WeatherAlertSeverity,
    WeatherAlertSnapshot,
    WeatherAlertSourceMetadata,
    WeatherAlertUrgency,
)
from rolling_thunder.http_home_platform import HttpResponse

NOW = datetime(2026, 8, 9, 6, 0, tzinfo=UTC)


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        body: bytes,
    ) -> None:
        self._status_code = status_code
        self._body = body

    @property
    def status_code(self) -> int:
        return self._status_code

    @property
    def body(self) -> bytes:
        return self._body


class RecordingTransport:
    def __init__(self, response: HttpResponse) -> None:
        self.response = response
        self.requests: list[
            tuple[str, str, Mapping[str, str], float]
        ] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_s: float,
    ) -> HttpResponse:
        assert body is None
        self.requests.append(
            (method, url, headers, timeout_s)
        )
        return self.response


def snapshot() -> WeatherAlertSnapshot:
    return WeatherAlertSnapshot(
        latitude=39.5245,
        longitude=-84.0625,
        fetched_at=NOW - timedelta(seconds=2),
        alerts=(
            WeatherAlertRecord(
                alert_id="urn:test:tornado-warning",
                event="Tornado Warning",
                severity=WeatherAlertSeverity.EXTREME,
                urgency=WeatherAlertUrgency.IMMEDIATE,
                certainty=WeatherAlertCertainty.OBSERVED,
                headline="Tornado Warning issued",
                area_description="Test Area",
                sent_at=NOW - timedelta(minutes=5),
                effective_at=NOW - timedelta(minutes=5),
                onset_at=NOW - timedelta(minutes=5),
                ends_at=NOW + timedelta(minutes=20),
                expires_at=NOW + timedelta(minutes=30),
            ),
        ),
        source=WeatherAlertSourceMetadata(
            provider_id="nws",
            provider_name="National Weather Service",
            attribution_text="National Weather Service alerts",
            attribution_url="https://www.weather.gov/",
        ),
    )


def payload() -> bytes:
    snap = snapshot()

    return dumps(
        {
            "api_schema_version": "1",
            "revision": 7,
            "snapshot": snap.model_dump(mode="json"),
            "health": {
                "status": "healthy",
                "applicability": "verified_current",
                "revision": 7,
                "last_attempt_at": NOW.isoformat(),
                "last_success_at": NOW.isoformat(),
                "last_error": None,
                "startup_storage_error": None,
                "persistence_error": None,
            },
        }
    ).encode("utf-8")


def test_client_fetches_exact_private_alert_endpoint() -> None:
    transport = RecordingTransport(
        FakeResponse(200, payload())
    )
    client = HttpForgeWeatherAlertClient(
        "http://forge:8766/",
        timeout_s=3.0,
        transport=transport,
        clock=lambda: NOW,
    )

    result = client.fetch_alerts()

    assert result.revision == 7
    assert result.snapshot == snapshot()
    assert (
        result.health.applicability
        is WeatherAlertApplicability.VERIFIED_CURRENT
    )
    assert result.received_at == NOW

    assert len(transport.requests) == 1
    method, url, headers, timeout = transport.requests[0]

    assert method == "GET"
    assert url == "http://forge:8766/api/v1/weather-alerts"
    assert headers["Accept"] == "application/json"
    assert headers["User-Agent"] == "RollingThunder-v4.1"
    assert timeout == 3.0


def test_client_accepts_verified_empty_active_set() -> None:
    snap = snapshot().model_copy(
        update={"alerts": ()}
    )
    raw = {
        "api_schema_version": "1",
        "revision": 8,
        "snapshot": snap.model_dump(mode="json"),
        "health": {
            "status": WeatherAlertProviderStatus.HEALTHY.value,
            "applicability": (
                WeatherAlertApplicability.VERIFIED_CURRENT.value
            ),
            "revision": 8,
        },
    }

    client = HttpForgeWeatherAlertClient(
        "http://forge:8766",
        transport=RecordingTransport(
            FakeResponse(
                200,
                dumps(raw).encode("utf-8"),
            )
        ),
        clock=lambda: NOW,
    )

    result = client.fetch_alerts()

    assert result.snapshot is not None
    assert result.snapshot.alerts == ()


def test_client_rejects_revision_mismatch() -> None:
    raw = __import__("json").loads(payload())
    raw["health"]["revision"] = 99

    client = HttpForgeWeatherAlertClient(
        "http://forge:8766",
        transport=RecordingTransport(
            FakeResponse(
                200,
                dumps(raw).encode("utf-8"),
            )
        ),
        clock=lambda: NOW,
    )

    with pytest.raises(
        ForgeWeatherAlertClientValidationError,
        match="revision",
    ):
        client.fetch_alerts()


def test_client_rejects_failed_http_and_bad_json() -> None:
    failed = HttpForgeWeatherAlertClient(
        "http://forge:8766",
        transport=RecordingTransport(
            FakeResponse(503, b"{}")
        ),
        clock=lambda: NOW,
    )
    malformed = HttpForgeWeatherAlertClient(
        "http://forge:8766",
        transport=RecordingTransport(
            FakeResponse(200, b"not-json")
        ),
        clock=lambda: NOW,
    )

    with pytest.raises(
        ForgeWeatherAlertClientTransportError,
        match="HTTP 503",
    ):
        failed.fetch_alerts()

    with pytest.raises(
        ForgeWeatherAlertClientValidationError,
        match="UTF-8 JSON",
    ):
        malformed.fetch_alerts()
