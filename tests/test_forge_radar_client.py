"""Tests for the Pi-side versioned Forge radar client contract."""

from collections.abc import Mapping
from datetime import UTC, datetime
from io import BytesIO
from json import dumps
from zipfile import ZIP_STORED, ZipFile

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


def coverage_archive(keys: tuple[MapTileKey, ...], *, body: bytes | None = None) -> bytes:
    output = BytesIO()
    tile_body = png_tile() if body is None else body
    with ZipFile(output, mode="w", compression=ZIP_STORED) as archive:
        for key in keys:
            archive.writestr(f"{key.zoom}/{key.x}/{key.y}.png", tile_body)
    return output.getvalue()


def test_client_validates_manifest_and_prefetches_coverage_for_tiles() -> None:
    # At zoom 2, x=1/y=1 clips the standard 20x16 prefetch block to 3x3.
    expected = tuple(
        MapTileKey(zoom=2, x=x, y=y)
        for x in range(1, 4)
        for y in range(1, 4)
    )
    transport = QueueTransport(
        [
            FakeResponse(200, manifest_payload()),
            FakeResponse(200, coverage_archive(expected)),
        ]
    )
    client = HttpForgeRadarClient(
        "http://192.168.9.170:8766",
        transport=transport,
        clock=lambda: NOW,
    )

    manifest = client.fetch_manifest()
    tile = client.fetch_tile(TOKEN, MapTileKey(zoom=2, x=1, y=1))
    cached_neighbor = client.fetch_tile(TOKEN, MapTileKey(zoom=2, x=2, y=2))

    assert manifest.revision == 4
    assert manifest.frame is not None
    assert manifest.frame.frame_token == TOKEN
    assert manifest.received_at == NOW
    assert tile.startswith(b"\x89PNG\r\n\x1a\n")
    assert cached_neighbor.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(transport.requests) == 2
    assert transport.requests[0][1].endswith("/api/v1/radar")
    assert transport.requests[1][1].endswith(
        f"/api/v1/radar/coverage/{TOKEN}/2/1/1/3/3.zip"
    )
    assert transport.requests[1][3] == 30.0


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


def test_client_rejects_non_png_inside_coverage_archive() -> None:
    key = MapTileKey(zoom=2, x=1, y=1)
    client = HttpForgeRadarClient(
        "http://192.168.9.170:8766",
        transport=QueueTransport(
            [FakeResponse(200, coverage_archive((key,), body=b"not-a-png"))]
        ),
        clock=lambda: NOW,
    )

    with pytest.raises(ForgeRadarResponseError, match="invalid PNG"):
        client.fetch_coverage(
            TOKEN,
            zoom=2,
            x_start=1,
            y_start=1,
            columns=1,
            rows=1,
        )


def test_client_rejects_archive_with_missing_or_unexpected_tiles() -> None:
    requested = MapTileKey(zoom=2, x=1, y=1)
    wrong = MapTileKey(zoom=2, x=2, y=1)
    client = HttpForgeRadarClient(
        "http://192.168.9.170:8766",
        transport=QueueTransport([FakeResponse(200, coverage_archive((wrong,)))]),
        clock=lambda: NOW,
    )

    with pytest.raises(ForgeRadarResponseError, match="did not match"):
        client.fetch_coverage(
            TOKEN,
            zoom=requested.zoom,
            x_start=requested.x,
            y_start=requested.y,
            columns=1,
            rows=1,
        )
