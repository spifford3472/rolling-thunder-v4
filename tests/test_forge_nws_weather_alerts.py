"""Tests for the National Weather Service point-alert provider boundary."""

from collections.abc import Mapping
from datetime import UTC, datetime
from json import dumps
from urllib.parse import parse_qs, urlsplit

import pytest

from rolling_thunder.forge_mobile_location import MobileLocationRecord
from rolling_thunder.forge_nws_weather_alerts import NwsWeatherAlertProvider
from rolling_thunder.forge_weather_alerts import (
    ForgeWeatherAlertProviderError,
    WeatherAlertCertainty,
    WeatherAlertSeverity,
    WeatherAlertUrgency,
)
from rolling_thunder.http_home_platform import HttpResponse

FETCHED_AT = datetime(2026, 8, 9, 5, 30, tzinfo=UTC)


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
    def __init__(self, response: HttpResponse) -> None:
        self.response = response
        self.requests: list[tuple[str, str, Mapping[str, str], float]] = []

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
        self.requests.append((method, url, headers, timeout_s))
        return self.response


def location() -> MobileLocationRecord:
    return MobileLocationRecord(
        latitude=39.524492,
        longitude=-84.062475,
        fix_at=datetime(2026, 8, 9, 5, 29, 55, tzinfo=UTC),
        received_at=datetime(2026, 8, 9, 5, 29, 56, tzinfo=UTC),
    )


def feature(
    alert_id: str,
    event: str,
    *,
    severity: str = "Severe",
    status: str = "Actual",
    message_type: str = "Alert",
) -> dict[str, object]:
    return {
        "id": alert_id,
        "type": "Feature",
        "geometry": None,
        "properties": {
            "status": status,
            "messageType": message_type,
            "sent": "2026-08-09T01:25:00-04:00",
            "effective": "2026-08-09T01:25:00-04:00",
            "onset": "2026-08-09T01:27:00-04:00",
            "ends": "2026-08-09T02:00:00-04:00",
            "expires": "2026-08-09T02:05:00-04:00",
            "severity": severity,
            "certainty": "Observed",
            "urgency": "Immediate",
            "event": event,
            "headline": f"{event} issued for Test Area",
            "areaDesc": "Test Area; Another Test Area",
        },
    }


def payload(*features: dict[str, object]) -> bytes:
    return dumps(
        {
            "@context": {"@version": "1.1"},
            "type": "FeatureCollection",
            "features": list(features),
        }
    ).encode("utf-8")


def test_provider_queries_exact_point_with_required_headers_and_normalizes() -> None:
    transport = RecordingTransport(
        FakeResponse(
            200,
            payload(
                feature(
                    "https://api.weather.gov/alerts/tornado-test",
                    "Tornado Warning",
                    severity="Extreme",
                ),
                feature(
                    "https://api.weather.gov/alerts/thunderstorm-test",
                    "Severe Thunderstorm Warning",
                ),
            ),
        )
    )
    provider = NwsWeatherAlertProvider(
        user_agent="RollingThunder/4 KI5VNB",
        transport=transport,
        timeout_s=4.0,
        now=lambda: FETCHED_AT,
    )

    snapshot = provider.fetch_alerts(location())

    assert len(transport.requests) == 1
    method, url, headers, timeout_s = transport.requests[0]
    assert method == "GET"
    assert urlsplit(url).path == "/alerts/active"
    assert parse_qs(urlsplit(url).query) == {"point": ["39.5245,-84.0625"]}
    assert headers["Accept"] == "application/geo+json"
    assert headers["User-Agent"] == "RollingThunder/4 KI5VNB"
    assert timeout_s == 4.0

    assert snapshot.latitude == 39.5245
    assert snapshot.longitude == -84.0625
    assert snapshot.fetched_at == FETCHED_AT
    assert snapshot.source.provider_id == "nws"
    assert snapshot.source.provider_name == "National Weather Service"
    assert [item.event for item in snapshot.alerts] == [
        "Tornado Warning",
        "Severe Thunderstorm Warning",
    ]
    tornado = snapshot.alerts[0]
    assert tornado.severity is WeatherAlertSeverity.EXTREME
    assert tornado.urgency is WeatherAlertUrgency.IMMEDIATE
    assert tornado.certainty is WeatherAlertCertainty.OBSERVED
    assert tornado.effective_at == datetime(2026, 8, 9, 5, 25, tzinfo=UTC)
    assert tornado.ends_at == datetime(2026, 8, 9, 6, 0, tzinfo=UTC)
    assert tornado.area_description == "Test Area; Another Test Area"


def test_successful_empty_feature_collection_is_valid_no_alerts_state() -> None:
    provider = NwsWeatherAlertProvider(
        user_agent="RollingThunder/4 test",
        transport=RecordingTransport(FakeResponse(200, payload())),
        now=lambda: FETCHED_AT,
    )

    snapshot = provider.fetch_alerts(location())

    assert snapshot.alerts == ()
    assert snapshot.fetched_at == FETCHED_AT


def test_provider_filters_non_actual_and_cancelled_features() -> None:
    provider = NwsWeatherAlertProvider(
        user_agent="RollingThunder/4 test",
        transport=RecordingTransport(
            FakeResponse(
                200,
                payload(
                    feature(
                        "https://api.weather.gov/alerts/test-message",
                        "Test Message",
                        status="Test",
                    ),
                    feature(
                        "https://api.weather.gov/alerts/cancel-message",
                        "Tornado Warning",
                        message_type="Cancel",
                    ),
                    feature(
                        "https://api.weather.gov/alerts/actual-message",
                        "Flash Flood Warning",
                    ),
                ),
            )
        ),
        now=lambda: FETCHED_AT,
    )

    snapshot = provider.fetch_alerts(location())

    assert [item.event for item in snapshot.alerts] == ["Flash Flood Warning"]


def test_provider_maps_unknown_cap_tokens_to_owned_unknown_values() -> None:
    raw = feature(
        "https://api.weather.gov/alerts/unknown-token",
        "Special Weather Statement",
        severity="UnexpectedProviderValue",
    )
    properties = raw["properties"]
    assert isinstance(properties, dict)
    properties["urgency"] = "Surprise"
    properties["certainty"] = "Maybe-ish"
    provider = NwsWeatherAlertProvider(
        user_agent="RollingThunder/4 test",
        transport=RecordingTransport(FakeResponse(200, payload(raw))),
        now=lambda: FETCHED_AT,
    )

    item = provider.fetch_alerts(location()).alerts[0]

    assert item.severity is WeatherAlertSeverity.UNKNOWN
    assert item.urgency is WeatherAlertUrgency.UNKNOWN
    assert item.certainty is WeatherAlertCertainty.UNKNOWN


def test_provider_rejects_duplicate_alert_ids() -> None:
    duplicate = "https://api.weather.gov/alerts/duplicate"
    provider = NwsWeatherAlertProvider(
        user_agent="RollingThunder/4 test",
        transport=RecordingTransport(
            FakeResponse(
                200,
                payload(
                    feature(duplicate, "Tornado Warning"),
                    feature(duplicate, "Severe Thunderstorm Warning"),
                ),
            )
        ),
        now=lambda: FETCHED_AT,
    )

    with pytest.raises(ForgeWeatherAlertProviderError, match="repeated alert id"):
        provider.fetch_alerts(location())


def test_provider_rejects_http_failure_invalid_json_and_bad_feature_schema() -> None:
    failed = NwsWeatherAlertProvider(
        user_agent="RollingThunder/4 test",
        transport=RecordingTransport(FakeResponse(503, b"{}")),
        now=lambda: FETCHED_AT,
    )
    malformed = NwsWeatherAlertProvider(
        user_agent="RollingThunder/4 test",
        transport=RecordingTransport(FakeResponse(200, b"not-json")),
        now=lambda: FETCHED_AT,
    )
    bad_schema = NwsWeatherAlertProvider(
        user_agent="RollingThunder/4 test",
        transport=RecordingTransport(
            FakeResponse(200, dumps({"features": {}}).encode("utf-8"))
        ),
        now=lambda: FETCHED_AT,
    )

    with pytest.raises(ForgeWeatherAlertProviderError, match="HTTP 503"):
        failed.fetch_alerts(location())
    with pytest.raises(ForgeWeatherAlertProviderError, match="valid UTF-8 JSON"):
        malformed.fetch_alerts(location())
    with pytest.raises(ForgeWeatherAlertProviderError, match="features must be an array"):
        bad_schema.fetch_alerts(location())


def test_provider_requires_nonblank_user_agent_and_https_endpoint() -> None:
    with pytest.raises(ValueError, match="User-Agent"):
        NwsWeatherAlertProvider(user_agent="   ")
    with pytest.raises(ValueError, match="HTTPS"):
        NwsWeatherAlertProvider(
            user_agent="RollingThunder/4 test",
            endpoint="http://api.weather.gov/alerts/active",
        )
