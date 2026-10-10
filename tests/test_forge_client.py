"""Tests for the typed Raspberry Pi Forge shared-spot client."""

from collections.abc import Mapping
from datetime import UTC, datetime
from json import dumps
from urllib.error import URLError

import pytest

from rolling_thunder.forge_client import (
    ForgeClientConnectionError,
    ForgeClientResponseError,
    ForgeClientValidationError,
    ForgeRemoteProviderStatus,
    HttpForgeSpotClient,
)
from rolling_thunder.http_home_platform import HttpResponse
from rolling_thunder.spot_domain import DxSpotIdentity, PotaSpotIdentity, SpotProvider

BASE_TIME = datetime(2026, 8, 7, 23, 30, tzinfo=UTC)


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
    def __init__(
        self,
        response: HttpResponse | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.response = response or FakeResponse(200, response_body())
        self.error = error
        self.requests: list[
            tuple[str, str, Mapping[str, str], bytes | None, float]
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
        self.requests.append((method, url, dict(headers), body, timeout_s))
        if self.error is not None:
            raise self.error
        return self.response


def payload() -> dict[str, object]:
    return {
        "api_schema_version": "1",
        "snapshot_revision": 9,
        "generated_at": "2026-08-07T23:29:00Z",
        "spots": [
            {
                "identity": {
                    "provider": "dx",
                    "callsign": "K1ABC",
                    "frequency": 14_025_000,
                },
                "callsign": "K1ABC",
                "operator_name": "DX Operator",
                "grid": "FN31pr",
                "frequency": 14_025_000,
                "mode": "CW",
                "display_mode": "CW",
                "spotted_at": "2026-08-07T23:28:00Z",
                "source_metadata": [
                    {"key": "spotter", "value": "W1AW"},
                ],
                "pota": None,
            },
            {
                "identity": {
                    "provider": "pota",
                    "park_reference": "US-1234",
                    "frequency": 14_250_000,
                },
                "callsign": "KI5VNB",
                "operator_name": "Geoff Kline",
                "grid": "EM79xm",
                "frequency": 14_250_000,
                "mode": "USB",
                "display_mode": "SSB",
                "spotted_at": "2026-08-07T23:28:30Z",
                "source_metadata": [
                    {"key": "comments", "value": "Portable activation"},
                ],
                "pota": {
                    "park_reference": "US-1234",
                    "park_name": "Example State Park",
                    "location_code": "US-OH",
                    "latitude": 39.75,
                    "longitude": -84.2,
                },
            },
        ],
        "providers": [
            {
                "provider": "dx",
                "status": "healthy",
                "active_spot_count": 1,
                "last_attempt_at": "2026-08-07T23:29:00Z",
                "last_success_at": "2026-08-07T23:29:00Z",
                "last_error": None,
            },
            {
                "provider": "pota",
                "status": "degraded",
                "active_spot_count": 1,
                "last_attempt_at": "2026-08-07T23:29:00Z",
                "last_success_at": "2026-08-07T23:27:00Z",
                "last_error": "POTA provider unavailable",
            },
        ],
    }


def response_body(value: object | None = None) -> bytes:
    return dumps(payload() if value is None else value).encode("utf-8")


def client_for(
    transport: RecordingTransport,
    *,
    max_response_bytes: int = 1_048_576,
) -> HttpForgeSpotClient:
    return HttpForgeSpotClient(
        "http://forge.example.test:8765/",
        timeout_s=3.5,
        max_response_bytes=max_response_bytes,
        transport=transport,
        clock=lambda: BASE_TIME,
    )


def test_fetch_builds_expected_request_and_reconstructs_combined_snapshot() -> None:
    transport = RecordingTransport()

    result = client_for(transport).fetch_spots()

    assert transport.requests == [
        (
            "GET",
            "http://forge.example.test:8765/api/v1/spots",
            {
                "Accept": "application/json",
                "User-Agent": "RollingThunder-v4.1",
            },
            None,
            3.5,
        )
    ]
    assert result.snapshot_revision == 9
    assert result.snapshot.generated_at == datetime(2026, 8, 7, 23, 29, tzinfo=UTC)
    assert result.received_at == BASE_TIME
    assert tuple(spot.provider for spot in result.snapshot.spots) == (
        SpotProvider.DX,
        SpotProvider.POTA,
    )

    dx, pota = result.snapshot.spots
    assert isinstance(dx.identity, DxSpotIdentity)
    assert dx.identity.stable_key == "dx:K1ABC:14025000"
    assert dx.operator_name == "DX Operator"
    assert dx.grid == "FN31pr"
    assert dx.frequency.hz == 14_025_000
    assert dx.source_metadata[0].key == "spotter"

    assert isinstance(pota.identity, PotaSpotIdentity)
    assert pota.identity.stable_key == "pota:KI5VNB:US-1234:14250000"
    assert pota.operator_name == "Geoff Kline"
    assert pota.grid == "EM79xm"
    assert pota.pota is not None
    assert pota.pota.park_name == "Example State Park"
    assert pota.pota.latitude == 39.75
    assert pota.pota.longitude == -84.2

    assert tuple(item.provider for item in result.providers) == (
        SpotProvider.DX,
        SpotProvider.POTA,
    )
    assert result.providers[0].status is ForgeRemoteProviderStatus.HEALTHY
    assert result.providers[1].status is ForgeRemoteProviderStatus.DEGRADED
    assert result.providers[1].last_error == "POTA provider unavailable"


def test_transport_failure_is_typed_and_does_not_expose_transport_text() -> None:
    transport = RecordingTransport(error=URLError("secret network detail"))

    with pytest.raises(
        ForgeClientConnectionError,
        match="could not be completed",
    ) as error_info:
        client_for(transport).fetch_spots()

    assert "secret network detail" not in str(error_info.value)


def test_non_success_http_status_is_typed() -> None:
    transport = RecordingTransport(FakeResponse(503, b"service unavailable"))

    with pytest.raises(ForgeClientConnectionError, match="HTTP 503"):
        client_for(transport).fetch_spots()


def test_oversized_response_is_rejected_before_json_validation() -> None:
    body = response_body()
    transport = RecordingTransport(FakeResponse(200, body))

    with pytest.raises(ForgeClientResponseError, match="byte limit"):
        client_for(transport, max_response_bytes=len(body) - 1).fetch_spots()


def test_invalid_json_is_rejected() -> None:
    transport = RecordingTransport(FakeResponse(200, b"{not-json"))

    with pytest.raises(ForgeClientResponseError, match="UTF-8 JSON"):
        client_for(transport).fetch_spots()


def test_wrong_schema_version_is_rejected() -> None:
    value = payload()
    value["api_schema_version"] = "2"
    transport = RecordingTransport(FakeResponse(200, response_body(value)))

    with pytest.raises(ForgeClientValidationError, match="api_schema_version"):
        client_for(transport).fetch_spots()


def test_noncanonical_spot_order_is_rejected_instead_of_repaired() -> None:
    value = payload()
    spots = value["spots"]
    assert isinstance(spots, list)
    spots.reverse()
    transport = RecordingTransport(FakeResponse(200, response_body(value)))

    with pytest.raises(ForgeClientValidationError, match="canonical shared order"):
        client_for(transport).fetch_spots()


def test_identity_frequency_mismatch_is_rejected() -> None:
    value = payload()
    spots = value["spots"]
    assert isinstance(spots, list)
    dx = spots[0]
    assert isinstance(dx, dict)
    dx["frequency"] = 14_026_000
    transport = RecordingTransport(FakeResponse(200, response_body(value)))

    with pytest.raises(ForgeClientValidationError, match="frequency"):
        client_for(transport).fetch_spots()


def test_provider_health_count_must_match_complete_snapshot() -> None:
    value = payload()
    providers = value["providers"]
    assert isinstance(providers, list)
    dx_health = providers[0]
    assert isinstance(dx_health, dict)
    dx_health["active_spot_count"] = 2
    transport = RecordingTransport(FakeResponse(200, response_body(value)))

    with pytest.raises(ForgeClientValidationError, match="active spot count"):
        client_for(transport).fetch_spots()


def test_provider_health_order_is_rejected_when_not_deterministic() -> None:
    value = payload()
    providers = value["providers"]
    assert isinstance(providers, list)
    providers.reverse()
    transport = RecordingTransport(FakeResponse(200, response_body(value)))

    with pytest.raises(ForgeClientValidationError, match="provider order"):
        client_for(transport).fetch_spots()


def test_api_url_rejects_non_http_and_query_components() -> None:
    with pytest.raises(ValueError, match="HTTP or HTTPS"):
        HttpForgeSpotClient("file:///tmp/forge")

    with pytest.raises(ValueError, match="query string"):
        HttpForgeSpotClient("https://forge.example.test?token=not-allowed")
