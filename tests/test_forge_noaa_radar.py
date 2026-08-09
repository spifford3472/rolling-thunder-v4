"""Tests for NOAA/NWS exact-frame radar discovery and tile export."""

from collections.abc import Mapping
from datetime import UTC, datetime
from io import BytesIO
from json import dumps, loads
from urllib.parse import parse_qs, urlsplit

from PIL import Image

from rolling_thunder.forge_mobile_location import MobileLocationRecord
from rolling_thunder.forge_noaa_radar import NoaaNwsRadarProvider
from rolling_thunder.http_home_platform import HttpResponse
from rolling_thunder.map_tiles import MapTileKey
from rolling_thunder.radar_tiles import apply_radar_opacity, web_mercator_tile_bounds

OBSERVED = datetime(2026, 8, 9, 1, 30, tzinfo=UTC)


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


def location() -> MobileLocationRecord:
    return MobileLocationRecord(
        latitude=39.524492,
        longitude=-84.062475,
        fix_at=datetime(2026, 8, 9, 1, 29, 55, tzinfo=UTC),
        received_at=datetime(2026, 8, 9, 1, 29, 56, tzinfo=UTC),
    )


def png_tile(alpha: int = 200) -> bytes:
    output = BytesIO()
    Image.new("RGBA", (256, 256), (100, 120, 140, alpha)).save(output, format="PNG")
    return output.getvalue()


def test_provider_discovers_latest_covering_raster_and_locks_export_to_it() -> None:
    metadata = dumps(
        {
            "features": [
                {
                    "attributes": {
                        "objectid": 123,
                        "idp_validtime": int(OBSERVED.timestamp() * 1000),
                        "idp_validendtime": int(
                            OBSERVED.replace(minute=35).timestamp() * 1000
                        ),
                    }
                }
            ]
        }
    ).encode()
    transport = QueueTransport(
        [
            FakeResponse(status_code=200, body=metadata),
            FakeResponse(status_code=200, body=png_tile()),
        ]
    )
    provider = NoaaNwsRadarProvider(transport=transport, timeout_s=3.0)

    frame = provider.discover_latest(location())
    tile = provider.fetch_tile("123", MapTileKey(zoom=7, x=34, y=49))

    assert frame.provider_frame_id == "123"
    assert frame.observed_at == OBSERVED
    assert frame.source.provider_id == "noaa_nws_mrms"
    assert frame.source.attribution_text == "Radar: NOAA/NWS MRMS"
    assert tile.startswith(b"\x89PNG\r\n\x1a\n")

    discovery_query = parse_qs(urlsplit(transport.requests[0][1]).query)
    assert discovery_query["geometryType"] == ["esriGeometryPoint"]
    assert discovery_query["inSR"] == ["4326"]
    assert discovery_query["orderByFields"] == ["idp_validtime DESC"]

    export_query = parse_qs(urlsplit(transport.requests[1][1]).query)
    assert export_query["bboxSR"] == ["3857"]
    assert export_query["imageSR"] == ["3857"]
    assert export_query["size"] == ["256,256"]
    assert export_query["format"] == ["png32"]
    mosaic_rule = loads(export_query["mosaicRule"][0])
    assert mosaic_rule["mosaicMethod"] == "esriMosaicLockRaster"
    assert mosaic_rule["lockRasterIds"] == [123]


def test_web_mercator_bounds_cover_world_at_zoom_zero() -> None:
    xmin, ymin, xmax, ymax = web_mercator_tile_bounds(MapTileKey(zoom=0, x=0, y=0))

    assert round(xmin, 3) == -20_037_508.343
    assert round(ymin, 3) == -20_037_508.343
    assert round(xmax, 3) == 20_037_508.343
    assert round(ymax, 3) == 20_037_508.343


def test_fixed_radar_opacity_scales_existing_alpha() -> None:
    processed = apply_radar_opacity(png_tile(alpha=200), 0.55)

    with Image.open(BytesIO(processed)) as image:
        assert image.mode == "RGBA"
        assert image.getpixel((0, 0))[3] == 110
