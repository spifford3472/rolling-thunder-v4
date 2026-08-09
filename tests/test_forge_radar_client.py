"""Tests for the Pi-side versioned Forge radar client contract."""

from collections.abc import Mapping
from datetime import UTC, datetime
from io import BytesIO
from json import dumps

import pytest
from PIL import Image

from rolling_thunder.forge_radar_client import (
    ForgeRadarResponseError,
    ForgeRadarValidationError,
    HttpForgeRadarClient,
)
from rolling_thunder.http_home_platform import HttpResponse
from rolling_thunder.map_tiles import MapTileKey

NOW = datetime(2026, 8, 9, 2, 10, tzinfo=UTC)
TOKEN = "a" * 32


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


class QueueTransport:
    def __init__(self, responses: list[HttpResponse]) -> None:
        self.responses = responses
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
        return self.responses.pop(0)


def manifest_payload() -> bytes:
    return dumps(
        {
            "api_schema_version": "1",
            "revision": 4,
            "frame": {
                "frame_token": TOKEN,
                "observed_at": "2026-08-09T02:05:00Z",
                "fetched_at": "2026-08-09T02:06:00Z",
                "source": {
                    "provider_id": "noaa_nws_mrms",
                    "provider_name": "NOAA/NWS",
                    "product": "base_reflectivity",
                    "attribution_text": "Radar: NOAA/NWS MRMS",
                    "attribution_url": "https://radar.weather.gov/",
                },
            },
            "health": {
                "status": "healthy",
                "stale": False,
                "renderable": True,
                "revision": 4,
                "last_attempt_at": "2026-08-09T02:06:00Z",
                "last_success_at": "2026-08-09T02:06:00Z",
                "last_error": None,
            },
        }
    ).encode()


def png_tile() -> bytes:
    output = BytesIO()
    Image.new("RGBA", (256, 256), (10, 20, 30, 180)).save(output, format="PNG")
    return output.getvalue()


def test_client_validates_manifest_and_uses_opaque_token_for_tiles() -> None:
    transport = QueueTransport(
        [
            FakeResponse(200, manifest_payload()),
            FakeResponse(200, png_tile()),
        ]
    )
    client = HttpForgeRadarClient(
        "http://192.168.9.170:8766",
        transport=transport,
        clock=lambda: NOW,
    )

    manifest = client.fetch_manifest()
    tile = client.fetch_tile(TOKEN, MapTileKey(zoom=7, x=34, y=49))

    assert manifest.revision == 4
    assert manifest.frame is not None
    assert manifest.frame.frame_token == TOKEN
    assert manifest.received_at == NOW
    assert tile.startswith(b"\x89PNG\r\n\x1a\n")
    assert transport.requests[0][1].endswith("/api/v1/radar")
    assert transport.requests[1][1].endswith(f"/api/v1/radar/tiles/{TOKEN}/7/34/49.png")


def test_client_rejects_inconsistent_health_revision() -> None:
    payload = __import__("json").loads(manifest_payload())
    payload["health"]["revision"] = 3
    client = HttpForgeRadarClient(
        "http://192.168.9.170:8766",
        transport=QueueTransport([FakeResponse(200, dumps(payload).encode())]),
        clock=lambda: NOW,
    )

    with pytest.raises(ForgeRadarValidationError, match="health revision"):
        client.fetch_manifest()


def test_client_rejects_non_png_tile() -> None:
    client = HttpForgeRadarClient(
        "http://192.168.9.170:8766",
        transport=QueueTransport([FakeResponse(200, b"not-a-png")]),
        clock=lambda: NOW,
    )

    with pytest.raises(ForgeRadarResponseError, match="valid PNG"):
        client.fetch_tile(TOKEN, MapTileKey(zoom=7, x=34, y=49))
