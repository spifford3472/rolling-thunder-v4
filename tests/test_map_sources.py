"""Tests for installed raster MBTiles and local-first tile resolution."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

from PIL import Image

from rolling_thunder.map_sources import (
    InstalledMapRegistry,
    MapPackageStyle,
    MapTileResolver,
    MapTileSource,
    RasterMbtilesPackage,
)
from rolling_thunder.map_tiles import (
    CachedMapTile,
    MapTileClient,
    MapTileError,
    MapTileKey,
    StylePartitionedMapTileCache,
)

NOW = datetime(2026, 8, 3, 20, 0, tzinfo=UTC)
KEY = MapTileKey(zoom=3, x=2, y=3)
OUTSIDE_KEY = MapTileKey(zoom=3, x=0, y=0)


def png_tile(value: int) -> bytes:
    """Build one valid 256 by 256 PNG tile."""
    image = Image.new("RGB", (256, 256), (value, value, value))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def write_mbtiles(
    path: Path,
    *,
    key: MapTileKey = KEY,
    png: bytes | None = None,
    identifier: str = "ohio",
    style: str = "day",
    priority: int = 0,
    tile_format: str = "png",
    tile_scheme: str = "tms",
) -> None:
    """Create a minimal raster MBTiles package for testing."""
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE metadata (
            name TEXT NOT NULL,
            value TEXT NOT NULL
        );
        CREATE TABLE tiles (
            zoom_level INTEGER NOT NULL,
            tile_column INTEGER NOT NULL,
            tile_row INTEGER NOT NULL,
            tile_data BLOB NOT NULL,
            PRIMARY KEY (zoom_level, tile_column, tile_row)
        );
        """
    )
    metadata = {
        "name": f"Test package {identifier}",
        "format": tile_format,
        "scheme": tile_scheme,
        "bounds": "-84.82,38.40,-80.52,42.00",
        "minzoom": str(key.zoom),
        "maxzoom": str(key.zoom),
        "attribution": "© OpenStreetMap contributors",
        "version": "2026.08.03",
        "rolling_thunder_id": identifier,
        "rolling_thunder_style": style,
        "rolling_thunder_priority": str(priority),
    }
    connection.executemany(
        "INSERT INTO metadata(name, value) VALUES (?, ?)",
        metadata.items(),
    )

    if png is not None:
        tms_row = (1 << key.zoom) - 1 - key.y
        connection.execute(
            """
            INSERT INTO tiles(
                zoom_level,
                tile_column,
                tile_row,
                tile_data
            ) VALUES (?, ?, ?, ?)
            """,
            (key.zoom, key.x, tms_row, png),
        )

    connection.commit()
    connection.close()


class FakeCache:
    def __init__(
        self,
        entries: dict[MapTileKey, CachedMapTile] | None = None,
    ) -> None:
        self.entries = entries or {}
        self.reads: list[MapTileKey] = []
        self.writes: list[tuple[MapTileKey, bytes]] = []

    def read(self, key: MapTileKey) -> CachedMapTile | None:
        self.reads.append(key)
        return self.entries.get(key)

    def write(self, key: MapTileKey, png: bytes) -> None:
        self.writes.append((key, png))


class FakeOnline:
    def __init__(
        self,
        *,
        png: bytes | None = None,
        fail: bool = False,
    ) -> None:
        self.png = png or png_tile(90)
        self.fail = fail
        self.requests: list[MapTileKey] = []

    def fetch(self, key: MapTileKey) -> bytes:
        self.requests.append(key)
        if self.fail:
            raise MapTileError("offline")
        return self.png


def test_mbtiles_reads_xyz_key_using_tms_tile_row(tmp_path: Path) -> None:
    path = tmp_path / "ohio.mbtiles"
    expected = png_tile(20)
    write_mbtiles(path, png=expected)

    package = RasterMbtilesPackage(path)

    assert package.metadata.identifier == "ohio"
    assert package.metadata.style is MapPackageStyle.DAY
    assert package.metadata.bounds == (-84.82, 38.40, -80.52, 42.00)
    assert package.read(KEY) == expected

    package.close()
    package.close()


def test_registry_prefers_highest_priority_matching_style(
    tmp_path: Path,
) -> None:
    low_path = tmp_path / "low.mbtiles"
    high_path = tmp_path / "high.mbtiles"
    night_path = tmp_path / "night.mbtiles"

    write_mbtiles(
        low_path,
        png=png_tile(10),
        identifier="low",
        priority=10,
    )
    write_mbtiles(
        high_path,
        png=png_tile(30),
        identifier="high",
        priority=30,
    )
    write_mbtiles(
        night_path,
        png=png_tile(80),
        identifier="night",
        style="night",
        priority=100,
    )

    registry = InstalledMapRegistry.load((low_path, high_path, night_path))

    result = registry.read(KEY, style=MapPackageStyle.DAY)

    assert result is not None
    assert result.package.identifier == "high"
    assert result.png == png_tile(30)
    assert [item.identifier for item in registry.packages] == [
        "night",
        "high",
        "low",
    ]

    registry.close()


def test_resolver_uses_installed_package_before_cache_and_network(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ohio.mbtiles"
    installed_png = png_tile(40)
    write_mbtiles(path, png=installed_png)

    cache = FakeCache(
        {
            KEY: CachedMapTile(
                png=png_tile(50),
                stored_at=NOW,
                is_fresh=True,
            )
        }
    )
    online = FakeOnline(png=png_tile(60))
    resolver = MapTileResolver(
        InstalledMapRegistry.load((path,)),
        cache,
        online,
    )

    result = resolver.read_local(KEY)

    assert result.png == installed_png
    assert result.source is MapTileSource.INSTALLED
    assert result.package_id == "ohio"
    assert result.attribution == "© OpenStreetMap contributors"
    assert cache.reads == []
    assert online.requests == []

    resolver.close()


def test_resolver_falls_back_to_stale_cache_when_network_fails() -> None:
    stale = CachedMapTile(
        png=png_tile(70),
        stored_at=NOW,
        is_fresh=False,
    )
    cache = FakeCache({KEY: stale})
    online = FakeOnline(fail=True)
    resolver = MapTileResolver(
        InstalledMapRegistry(),
        cache,
        online,
    )

    local = resolver.read_local(KEY)
    refreshed = resolver.refresh_online(KEY, local)

    assert local.source is MapTileSource.STALE_CACHE
    assert local.attribution == "© OpenStreetMap contributors"
    assert refreshed == local
    assert online.requests == [KEY]
    assert cache.writes == []

    resolver.close()


def test_missing_or_invalid_package_does_not_block_cache(
    tmp_path: Path,
) -> None:
    invalid_path = tmp_path / "invalid.mbtiles"
    write_mbtiles(
        invalid_path,
        png=png_tile(10),
        tile_format="pbf",
    )
    missing_path = tmp_path / "missing.mbtiles"

    cached = CachedMapTile(
        png=png_tile(75),
        stored_at=NOW,
        is_fresh=True,
    )
    registry = InstalledMapRegistry.load((invalid_path, missing_path))
    resolver = MapTileResolver(
        registry,
        FakeCache({KEY: cached}),
        FakeOnline(),
    )

    result = resolver.read_local(KEY)

    assert result.png == cached.png
    assert result.source is MapTileSource.CACHE
    assert len(resolver.diagnostics) == 2

    resolver.close()


def test_package_declared_bounds_define_tile_coverage(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ohio.mbtiles"
    write_mbtiles(path, png=png_tile(20))

    package = RasterMbtilesPackage(path)

    assert package.metadata.covers(KEY) is True
    assert package.metadata.covers(OUTSIDE_KEY) is False

    package.close()


def test_missing_tile_inside_installed_coverage_never_uses_network(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ohio.mbtiles"
    write_mbtiles(path)

    cache = FakeCache()
    online = FakeOnline()
    resolver = MapTileResolver(
        InstalledMapRegistry.load((path,)),
        cache,
        online,
    )

    local = resolver.read_local(KEY)
    refreshed = resolver.refresh_online(KEY, local)

    assert local.png is None
    assert local.source is MapTileSource.MISSING
    assert local.online_refresh_allowed is False
    assert refreshed == local
    assert cache.reads == [KEY]
    assert online.requests == []
    assert cache.writes == []

    resolver.close()


def test_missing_tile_outside_installed_coverage_may_use_network(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ohio.mbtiles"
    write_mbtiles(path)

    cache = FakeCache()
    online = FakeOnline(png=png_tile(85))
    resolver = MapTileResolver(
        InstalledMapRegistry.load((path,)),
        cache,
        online,
    )

    local = resolver.read_local(OUTSIDE_KEY)
    refreshed = resolver.refresh_online(OUTSIDE_KEY, local)

    assert local.source is MapTileSource.MISSING
    assert local.online_refresh_allowed is True
    assert refreshed.source is MapTileSource.NETWORK
    assert refreshed.png == png_tile(85)
    assert online.requests == [OUTSIDE_KEY]
    assert cache.writes == [(OUTSIDE_KEY, png_tile(85))]

    resolver.close()


def test_night_resolver_never_reuses_day_cache_with_unstyled_source(
    tmp_path: Path,
) -> None:
    day = png_tile(230)
    cache = StylePartitionedMapTileCache(
        tmp_path,
        style="day",
        clock=lambda: NOW,
    )
    cache.write_for_style(KEY, day, "day")
    resolver = MapTileResolver(
        InstalledMapRegistry(),
        cache,
        MapTileClient(
            "https://tiles.example.invalid/{z}/{x}/{y}.png",
            require_style_token_for_night=True,
        ),
        style=MapPackageStyle.NIGHT,
    )

    local = resolver.read_local(KEY)
    refreshed = resolver.refresh_online(KEY, local)

    assert local.png is None
    assert local.source is MapTileSource.MISSING
    assert refreshed == local
    day_result = cache.read_for_style(KEY, "day")
    assert day_result is not None
    assert day_result.png == day

    resolver.close()


def test_mbtiles_rejects_non_tms_tile_scheme(
    tmp_path: Path,
) -> None:
    path = tmp_path / "xyz.mbtiles"
    write_mbtiles(
        path,
        png=png_tile(25),
        tile_scheme="xyz",
    )

    registry = InstalledMapRegistry.load((path,))

    assert registry.packages == ()
    assert len(registry.errors) == 1
    assert "TMS tile scheme" in registry.errors[0]

    registry.close()
