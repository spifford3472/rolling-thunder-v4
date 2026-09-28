"""Tests for raster-map tile math, validation, retrieval, and caching."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from rolling_thunder.live_map import GeoPoint
from rolling_thunder.map_tiles import (
    DEFAULT_MAP_USER_AGENT,
    MAX_WEB_MERCATOR_LATITUDE,
    MapTileCache,
    MapTileClient,
    MapTileError,
    MapTileKey,
    build_map_viewport,
    validate_map_tile_png,
    web_mercator_world_pixel,
)

NOW = datetime(2026, 8, 2, 20, 0, tzinfo=UTC)


def png_tile(value: int = 20) -> bytes:
    image = Image.new("RGB", (256, 256), (value, value, value))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


@dataclass(frozen=True)
class FakeResponse:
    status_code: int
    body: bytes


class RecordingTransport:
    def __init__(
        self,
        response: FakeResponse | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response = response or FakeResponse(200, png_tile())
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
    ) -> FakeResponse:
        self.requests.append((method, url, headers, body, timeout_s))
        if self.error is not None:
            raise self.error
        return self.response


class CountingPruneMapTileCache(MapTileCache):
    """Record full prune passes while preserving the real cache behavior."""

    def __init__(
        self,
        root: Path,
        *,
        maximum_tiles: int = 2_048,
        prune_interval_writes: int,
        clock: Callable[[], datetime],
    ) -> None:
        self.prune_calls = 0
        super().__init__(
            root,
            maximum_tiles=maximum_tiles,
            prune_interval_writes=prune_interval_writes,
            clock=clock,
        )

    def _prune(self) -> None:
        self.prune_calls += 1
        super()._prune()


def test_web_mercator_places_zero_zero_at_world_center() -> None:
    assert web_mercator_world_pixel(GeoPoint(0, 0), 0) == (128.0, 128.0)


def test_web_mercator_clamps_polar_latitudes() -> None:
    north = web_mercator_world_pixel(GeoPoint(90, 0), 3)
    limit = web_mercator_world_pixel(
        GeoPoint(MAX_WEB_MERCATOR_LATITUDE, 0),
        3,
    )
    assert north == pytest.approx(limit)


def test_viewport_builds_wrapped_visible_tiles() -> None:
    viewport = build_map_viewport(
        GeoPoint(0, 179.9),
        zoom=2,
        width_px=512,
        height_px=256,
    )

    assert viewport.width_px == 512
    assert viewport.height_px == 256
    assert viewport.tile_keys
    assert all(0 <= key.x < 4 for key in viewport.tile_keys)
    assert {key.x for key in viewport.tile_keys} == {0, 2, 3}


def test_viewport_rejects_invalid_dimensions() -> None:
    with pytest.raises(ValueError, match="dimensions"):
        build_map_viewport(GeoPoint(0, 0), zoom=13, width_px=0, height_px=100)


def test_tile_client_uses_configured_url_headers_and_timeout() -> None:
    transport = RecordingTransport()
    client = MapTileClient(
        "https://tiles.example.invalid/{z}/{x}/{y}.png",
        timeout_s=3.5,
        transport=transport,
    )

    result = client.fetch(MapTileKey(zoom=13, x=123, y=456))

    assert result == transport.response.body
    assert transport.requests == [
        (
            "GET",
            "https://tiles.example.invalid/13/123/456.png",
            {
                "Accept": "image/png",
                "User-Agent": DEFAULT_MAP_USER_AGENT,
            },
            None,
            3.5,
        )
    ]


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (FakeResponse(503, b""), "HTTP 503"),
        (FakeResponse(200, b"not an image"), "invalid image"),
        (FakeResponse(200, b"x" * 2_000_001), "size limit"),
    ],
)
def test_tile_client_rejects_failed_or_unsafe_responses(
    response: FakeResponse,
    message: str,
) -> None:
    client = MapTileClient(
        "https://tiles.example.invalid/{z}/{x}/{y}.png",
        transport=RecordingTransport(response),
    )

    with pytest.raises(MapTileError, match=message):
        client.fetch(MapTileKey(zoom=1, x=0, y=0))


def test_tile_client_rejects_invalid_template() -> None:
    with pytest.raises(ValueError, match=r"\{y\}"):
        MapTileClient("https://tiles.example.invalid/{z}/{x}.png")


def test_png_validation_rejects_wrong_dimensions() -> None:
    output = BytesIO()
    Image.new("RGB", (64, 64)).save(output, format="PNG")

    with pytest.raises(MapTileError, match="256 by 256"):
        validate_map_tile_png(output.getvalue())


def test_cache_returns_fresh_tile_without_modifying_bytes(tmp_path: Path) -> None:
    cache = MapTileCache(tmp_path, clock=lambda: NOW)
    key = MapTileKey(zoom=2, x=1, y=2)
    original = png_tile(40)

    cache.write(key, original)
    result = cache.read(key)

    assert result is not None
    assert result.png == original
    assert result.is_fresh is True
    assert result.stored_at == NOW


def test_cache_returns_expired_tile_as_stale(tmp_path: Path) -> None:
    mutable_now = [NOW]
    cache = MapTileCache(
        tmp_path,
        retention=timedelta(days=7),
        clock=lambda: mutable_now[0],
    )
    key = MapTileKey(zoom=2, x=1, y=2)
    cache.write(key, png_tile())
    mutable_now[0] = NOW + timedelta(days=8)

    result = cache.read(key)

    assert result is not None
    assert result.is_fresh is False


def test_cache_removes_corrupt_entry(tmp_path: Path) -> None:
    cache = MapTileCache(tmp_path, clock=lambda: NOW)
    key = MapTileKey(zoom=2, x=1, y=2)
    path = tmp_path / "2" / "1" / "2.png"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"corrupt")

    assert cache.read(key) is None
    assert path.exists() is False


def test_cache_first_write_prunes_then_amortizes_full_scans(
    tmp_path: Path,
) -> None:
    mutable_now = [NOW]
    cache = CountingPruneMapTileCache(
        tmp_path,
        prune_interval_writes=3,
        clock=lambda: mutable_now[0],
    )
    keys = tuple(MapTileKey(zoom=3, x=1, y=index) for index in range(4))

    cache.write(keys[0], png_tile(20))
    assert cache.prune_calls == 1

    for index, key in enumerate(keys[1:3], start=1):
        mutable_now[0] = NOW + timedelta(seconds=index)
        cache.write(key, png_tile(20 + index))

    assert cache.prune_calls == 1

    mutable_now[0] = NOW + timedelta(seconds=3)
    cache.write(keys[3], png_tile(23))

    assert cache.prune_calls == 2


def test_cache_prune_cadence_bounds_temporary_overshoot(
    tmp_path: Path,
) -> None:
    mutable_now = [NOW]
    keys = tuple(MapTileKey(zoom=3, x=1, y=index) for index in range(6))
    seed = MapTileCache(
        tmp_path,
        maximum_tiles=2,
        prune_interval_writes=1,
        clock=lambda: mutable_now[0],
    )

    for index, key in enumerate(keys[:2]):
        mutable_now[0] = NOW + timedelta(seconds=index)
        seed.write(key, png_tile(20 + index))

    cache = MapTileCache(
        tmp_path,
        maximum_tiles=2,
        prune_interval_writes=3,
        clock=lambda: mutable_now[0],
    )

    mutable_now[0] = NOW + timedelta(seconds=2)
    cache.write(keys[2], png_tile(22))
    assert len(tuple(tmp_path.glob("*/*/*.png"))) == 2

    for index, key in enumerate(keys[3:5], start=3):
        mutable_now[0] = NOW + timedelta(seconds=index)
        cache.write(key, png_tile(20 + index))

    assert len(tuple(tmp_path.glob("*/*/*.png"))) == 4

    mutable_now[0] = NOW + timedelta(seconds=5)
    cache.write(keys[5], png_tile(25))

    assert len(tuple(tmp_path.glob("*/*/*.png"))) == 2
    assert cache.read(keys[4]) is not None
    assert cache.read(keys[5]) is not None


def test_cache_prunes_oldest_tiles_to_configured_bound(
    tmp_path: Path,
) -> None:
    mutable_now = [NOW]
    cache = MapTileCache(
        tmp_path,
        maximum_tiles=2,
        prune_interval_writes=1,
        clock=lambda: mutable_now[0],
    )
    keys = [
        MapTileKey(zoom=3, x=1, y=1),
        MapTileKey(zoom=3, x=1, y=2),
        MapTileKey(zoom=3, x=1, y=3),
    ]
    for index, key in enumerate(keys):
        mutable_now[0] = NOW + timedelta(seconds=index)
        cache.write(key, png_tile(20 + index))

    assert cache.read(keys[0]) is None
    assert cache.read(keys[1]) is not None
    assert cache.read(keys[2]) is not None


def test_cache_requires_at_least_seven_day_retention(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least seven days"):
        MapTileCache(tmp_path, retention=timedelta(days=6))


def test_cache_requires_positive_prune_interval(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="prune interval"):
        MapTileCache(tmp_path, prune_interval_writes=0)
