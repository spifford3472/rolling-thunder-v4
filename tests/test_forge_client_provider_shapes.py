"""Additional Forge client contract tests for provider-specific snapshot shapes."""

from collections.abc import Mapping
from datetime import UTC, datetime
from json import dumps

import pytest

from rolling_thunder.forge_client import (
    ForgeClientResponseError,
    HttpForgeSpotClient,
)
from rolling_thunder.http_home_platform import HttpResponse
from rolling_thunder.spot_domain import SpotProvider


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    @property
    def status_code(self) -> int:
        return 200

    @property
    def body(self) -> bytes:
        return self._body


class StaticTransport:
    def __init__(self, body: bytes) -> None:
        self.response = FakeResponse(body)

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_s: float,
    ) -> HttpResponse:
        assert method == "GET"
        assert url.endswith("/api/v1/spots")
        assert headers["Accept"] == "application/json"
        assert body is None
        assert timeout_s == 2.0
        return self.response


def _client(body: bytes) -> HttpForgeSpotClient:
    return HttpForgeSpotClient(
        "http://forge.example.test:8765",
        timeout_s=2.0,
        transport=StaticTransport(body),
        clock=lambda: datetime(2026, 8, 8, 0, 0, tzinfo=UTC),
    )


def _base_payload() -> dict[str, object]:
    return {
        "api_schema_version": "1",
        "snapshot_revision": 12,
        "generated_at": "2026-08-07T23:59:00Z",
    }


def test_dx_only_snapshot_is_accepted() -> None:
    payload = _base_payload()
    payload["spots"] = [
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
            "spotted_at": "2026-08-07T23:58:00Z",
            "source_metadata": [{"key": "spotter", "value": "W1AW"}],
            "pota": None,
        }
    ]
    payload["providers"] = [
        {
            "provider": "dx",
            "status": "healthy",
            "active_spot_count": 1,
            "last_attempt_at": "2026-08-07T23:59:00Z",
            "last_success_at": "2026-08-07T23:59:00Z",
            "last_error": None,
        }
    ]

    result = _client(dumps(payload).encode("utf-8")).fetch_spots()

    assert tuple(spot.provider for spot in result.snapshot.spots) == (SpotProvider.DX,)
    assert tuple(provider.provider for provider in result.providers) == (SpotProvider.DX,)


def test_pota_only_snapshot_is_accepted() -> None:
    payload = _base_payload()
    payload["spots"] = [
        {
            "identity": {
                "provider": "pota",
                "park_reference": "US-1234",
                "frequency": 14_250_000,
            },
            "callsign": "KI5VNB",
            "operator_name": "Example Operator",
            "grid": "EM79xm",
            "frequency": 14_250_000,
            "mode": "USB",
            "display_mode": "SSB",
            "spotted_at": "2026-08-07T23:58:30Z",
            "source_metadata": [{"key": "comments", "value": "Portable"}],
            "pota": {
                "park_reference": "US-1234",
                "park_name": "Example State Park",
                "location_code": "US-OH",
                "latitude": 39.75,
                "longitude": -84.2,
            },
        }
    ]
    payload["providers"] = [
        {
            "provider": "pota",
            "status": "healthy",
            "active_spot_count": 1,
            "last_attempt_at": "2026-08-07T23:59:00Z",
            "last_success_at": "2026-08-07T23:59:00Z",
            "last_error": None,
        }
    ]

    result = _client(dumps(payload).encode("utf-8")).fetch_spots()

    assert tuple(spot.provider for spot in result.snapshot.spots) == (SpotProvider.POTA,)
    assert result.snapshot.spots[0].pota is not None
    assert tuple(provider.provider for provider in result.providers) == (SpotProvider.POTA,)


def test_invalid_utf8_response_is_rejected() -> None:
    with pytest.raises(ForgeClientResponseError, match="UTF-8 JSON"):
        _client(b"\xff\xfe\xfa").fetch_spots()
