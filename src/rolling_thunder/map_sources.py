"""Local-first raster-map package discovery and tile resolution."""

from __future__ import annotations

import math
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from threading import Lock
from typing import Protocol

from rolling_thunder.map_tiles import (
    CachedMapTile,
    MapTileError,
    MapTileKey,
    validate_map_tile_png,
)

DEFAULT_MAP_ATTRIBUTION = "© OpenStreetMap contributors"

_WEB_MERCATOR_LATITUDE_LIMIT = 85.05112878


def _longitude_to_tile_x(longitude: float, zoom: int) -> int:
    """Convert longitude to a clamped XYZ tile column."""
    tile_count = 1 << zoom
    column = math.floor((longitude + 180.0) / 360.0 * tile_count)
    return min(max(column, 0), tile_count - 1)


def _latitude_to_tile_y(latitude: float, zoom: int) -> int:
    """Convert latitude to a clamped XYZ tile row."""
    tile_count = 1 << zoom
    clamped_latitude = min(
        max(latitude, -_WEB_MERCATOR_LATITUDE_LIMIT),
        _WEB_MERCATOR_LATITUDE_LIMIT,
    )
    latitude_radians = math.radians(clamped_latitude)
    row = math.floor((1.0 - math.asinh(math.tan(latitude_radians)) / math.pi) / 2.0 * tile_count)
    return min(max(row, 0), tile_count - 1)


class MapPackageError(RuntimeError):
    """Raised when an installed map package is unusable."""


class MapPackageStyle(StrEnum):
    """Supported installed raster-map visual styles."""

    DAY = "day"
    NIGHT = "night"


class MapTileSource(StrEnum):
    """Origin or availability of one resolved map tile."""

    INSTALLED = "installed"
    NETWORK = "network"
    CACHE = "cache"
    STALE_CACHE = "stale_cache"
    MISSING = "missing"


@dataclass(frozen=True)
class InstalledMapMetadata:
    """Validated metadata describing one raster MBTiles package."""

    identifier: str
    name: str
    bounds: tuple[float, float, float, float]
    min_zoom: int
    max_zoom: int
    attribution: str
    version: str
    style: MapPackageStyle
    priority: int

    def covers(self, key: MapTileKey) -> bool:
        """Return whether the declared package bounds cover one XYZ tile."""
        if not self.min_zoom <= key.zoom <= self.max_zoom:
            return False

        west, south, east, north = self.bounds

        minimum_x = _longitude_to_tile_x(west, key.zoom)
        maximum_x = _longitude_to_tile_x(east, key.zoom)
        minimum_y = _latitude_to_tile_y(north, key.zoom)
        maximum_y = _latitude_to_tile_y(south, key.zoom)

        return minimum_x <= key.x <= maximum_x and minimum_y <= key.y <= maximum_y


@dataclass(frozen=True)
class InstalledMapTile:
    """One tile returned by an installed package."""

    png: bytes
    package: InstalledMapMetadata


@dataclass(frozen=True)
class InstalledMapLookup:
    """Installed tile lookup plus declared offline-coverage state."""

    tile: InstalledMapTile | None
    covering_package: InstalledMapMetadata | None


@dataclass(frozen=True)
class ResolvedMapTile:
    """One tile result from the local-first resolution chain."""

    png: bytes | None
    source: MapTileSource
    package_id: str | None = None
    attribution: str | None = None
    online_refresh_allowed: bool = True


class RuntimeMapTileCache(Protocol):
    """Narrow cache boundary required by the map resolver."""

    def read(self, key: MapTileKey) -> CachedMapTile | None:
        """Return a cached tile when present."""

    def write(self, key: MapTileKey, png: bytes) -> None:
        """Persist one validated tile."""


class OnlineMapTileClient(Protocol):
    """Narrow online retrieval boundary required by the map resolver."""

    def fetch(self, key: MapTileKey) -> bytes:
        """Retrieve one validated tile or raise MapTileError."""


class RasterMbtilesPackage:
    """Read one validated raster MBTiles package through SQLite."""

    def __init__(self, path: Path) -> None:
        self._path = path.resolve()
        self._lock = Lock()
        self._closed = False

        try:
            self._connection = sqlite3.connect(
                f"{self._path.as_uri()}?mode=ro",
                uri=True,
                check_same_thread=False,
            )
        except sqlite3.Error as error:
            raise MapPackageError(
                f"Could not open installed map package {self._path}: {error}"
            ) from error

        try:
            self._metadata = self._load_metadata()
        except BaseException:
            self._connection.close()
            self._closed = True
            raise

    @property
    def path(self) -> Path:
        """Return the package file path."""
        return self._path

    @property
    def metadata(self) -> InstalledMapMetadata:
        """Return validated package metadata."""
        return self._metadata

    def read(self, key: MapTileKey) -> bytes | None:
        """Return one XYZ-addressed PNG tile from the MBTiles package."""
        if not self._metadata.min_zoom <= key.zoom <= self._metadata.max_zoom:
            return None

        tms_row = (1 << key.zoom) - 1 - key.y

        with self._lock:
            if self._closed:
                raise MapPackageError(f"Installed map package is closed: {self._path}")

            try:
                row = self._connection.execute(
                    """
                    SELECT tile_data
                    FROM tiles
                    WHERE zoom_level = ?
                      AND tile_column = ?
                      AND tile_row = ?
                    """,
                    (key.zoom, key.x, tms_row),
                ).fetchone()
            except sqlite3.Error as error:
                raise MapPackageError(
                    f"Could not read installed map package {self._path}: {error}"
                ) from error

        if row is None:
            return None

        raw = row[0]
        if not isinstance(raw, (bytes, bytearray, memoryview)):
            raise MapPackageError(
                f"Installed map package returned non-binary tile data: {self._path}"
            )

        try:
            return validate_map_tile_png(bytes(raw))
        except MapTileError as error:
            raise MapPackageError(
                f"Installed map package contains an invalid PNG tile: {self._path}"
            ) from error

    def close(self) -> None:
        """Close the read-only SQLite connection idempotently."""
        with self._lock:
            if self._closed:
                return
            self._connection.close()
            self._closed = True

    def _load_metadata(self) -> InstalledMapMetadata:
        try:
            rows = self._connection.execute("SELECT name, value FROM metadata").fetchall()
        except sqlite3.Error as error:
            raise MapPackageError(
                f"Could not read MBTiles metadata from {self._path}: {error}"
            ) from error

        metadata = {str(name).strip(): str(value).strip() for name, value in rows}

        name = self._required(metadata, "name")
        tile_format = self._required(metadata, "format").lower()
        if tile_format != "png":
            raise MapPackageError(
                f"Installed map package must contain PNG raster tiles: {self._path}"
            )

        tile_scheme = metadata.get("scheme", "tms").lower()
        if tile_scheme != "tms":
            raise MapPackageError(
                f"Installed map package must use the TMS tile scheme: {self._path}"
            )

        min_zoom = self._parse_zoom(metadata, "minzoom")
        max_zoom = self._parse_zoom(metadata, "maxzoom")
        if min_zoom > max_zoom:
            raise MapPackageError(f"Installed map package minzoom exceeds maxzoom: {self._path}")

        bounds = self._parse_bounds(self._required(metadata, "bounds"))
        attribution = self._required(metadata, "attribution")
        version = self._required(metadata, "version")

        identifier = metadata.get(
            "rolling_thunder_id",
            self._path.stem,
        ).strip()
        if not identifier:
            raise MapPackageError(f"Installed map package identifier is blank: {self._path}")

        raw_style = metadata.get(
            "rolling_thunder_style",
            MapPackageStyle.DAY.value,
        ).lower()
        try:
            style = MapPackageStyle(raw_style)
        except ValueError as error:
            raise MapPackageError(
                f"Installed map package has unsupported style {raw_style!r}: {self._path}"
            ) from error

        raw_priority = metadata.get("rolling_thunder_priority", "0")
        try:
            priority = int(raw_priority)
        except ValueError as error:
            raise MapPackageError(
                f"Installed map package priority must be an integer: {self._path}"
            ) from error

        return InstalledMapMetadata(
            identifier=identifier,
            name=name,
            bounds=bounds,
            min_zoom=min_zoom,
            max_zoom=max_zoom,
            attribution=attribution,
            version=version,
            style=style,
            priority=priority,
        )

    def _required(
        self,
        metadata: dict[str, str],
        key: str,
    ) -> str:
        value = metadata.get(key, "").strip()
        if not value:
            raise MapPackageError(
                f"Installed map package metadata is missing {key!r}: {self._path}"
            )
        return value

    def _parse_zoom(
        self,
        metadata: dict[str, str],
        key: str,
    ) -> int:
        raw = self._required(metadata, key)
        try:
            zoom = int(raw)
        except ValueError as error:
            raise MapPackageError(
                f"Installed map package {key} must be an integer: {self._path}"
            ) from error

        if not 0 <= zoom <= 22:
            raise MapPackageError(
                f"Installed map package {key} must be between 0 and 22: {self._path}"
            )
        return zoom

    def _parse_bounds(
        self,
        raw: str,
    ) -> tuple[float, float, float, float]:
        try:
            west, south, east, north = (float(part.strip()) for part in raw.split(","))
        except (TypeError, ValueError) as error:
            raise MapPackageError(
                f"Installed map package bounds must contain west,south,east,north: {self._path}"
            ) from error

        if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
            raise MapPackageError(f"Installed map package bounds are invalid: {self._path}")

        return west, south, east, north


class InstalledMapRegistry:
    """Own prioritized installed map packages and degradation details."""

    def __init__(
        self,
        packages: Iterable[RasterMbtilesPackage] = (),
        *,
        errors: Iterable[str] = (),
    ) -> None:
        self._packages = tuple(
            sorted(
                packages,
                key=lambda package: (
                    -package.metadata.priority,
                    package.metadata.identifier,
                ),
            )
        )
        self._errors = list(errors)
        self._lock = Lock()
        self._closed = False

    @classmethod
    def load(
        cls,
        paths: Iterable[Path],
    ) -> InstalledMapRegistry:
        """Load all usable packages and retain actionable failures."""
        packages: list[RasterMbtilesPackage] = []
        errors: list[str] = []

        for path in paths:
            try:
                packages.append(RasterMbtilesPackage(path))
            except MapPackageError as error:
                errors.append(str(error))

        return cls(packages, errors=errors)

    @property
    def packages(self) -> tuple[InstalledMapMetadata, ...]:
        """Return installed package metadata in lookup order."""
        return tuple(package.metadata for package in self._packages)

    @property
    def errors(self) -> tuple[str, ...]:
        """Return package loading or reading failures."""
        with self._lock:
            return tuple(self._errors)

    def lookup(
        self,
        key: MapTileKey,
        *,
        style: MapPackageStyle,
    ) -> InstalledMapLookup:
        """Resolve a tile while retaining declared package coverage."""
        with self._lock:
            if self._closed:
                return InstalledMapLookup(
                    tile=None,
                    covering_package=None,
                )
            packages = self._packages

        covering_package: InstalledMapMetadata | None = None

        for package in packages:
            metadata = package.metadata

            if metadata.style is not style:
                continue

            if not metadata.covers(key):
                continue

            if covering_package is None:
                covering_package = metadata

            try:
                png = package.read(key)
            except MapPackageError as error:
                with self._lock:
                    self._errors.append(str(error))
                continue

            if png is not None:
                return InstalledMapLookup(
                    tile=InstalledMapTile(
                        png=png,
                        package=metadata,
                    ),
                    covering_package=metadata,
                )

        return InstalledMapLookup(
            tile=None,
            covering_package=covering_package,
        )

    def read(
        self,
        key: MapTileKey,
        *,
        style: MapPackageStyle,
    ) -> InstalledMapTile | None:
        """Return the highest-priority installed tile for one style."""
        return self.lookup(key, style=style).tile

    def close(self) -> None:
        """Close every installed package idempotently."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            packages = self._packages

        for package in packages:
            package.close()


class MapTileResolver:
    """Resolve installed, cached, and online raster tiles in order."""

    def __init__(
        self,
        installed: InstalledMapRegistry,
        cache: RuntimeMapTileCache,
        online: OnlineMapTileClient,
        *,
        style: MapPackageStyle = MapPackageStyle.DAY,
        online_attribution: str = DEFAULT_MAP_ATTRIBUTION,
    ) -> None:
        normalized_attribution = online_attribution.strip()
        if not normalized_attribution:
            raise ValueError("Online map attribution must not be blank.")

        self._installed = installed
        self._cache = cache
        self._online = online
        self._style = style
        self._online_attribution = normalized_attribution

    @property
    def installed_packages(self) -> tuple[InstalledMapMetadata, ...]:
        """Return installed package metadata in lookup order."""
        return self._installed.packages

    @property
    def diagnostics(self) -> tuple[str, ...]:
        """Return non-fatal installed-package failures."""
        return self._installed.errors

    def read_local(self, key: MapTileKey) -> ResolvedMapTile:
        """Resolve installed package first, then the runtime cache."""
        installed = self._installed.lookup(
            key,
            style=self._style,
        )

        if installed.tile is not None:
            return ResolvedMapTile(
                png=installed.tile.png,
                source=MapTileSource.INSTALLED,
                package_id=installed.tile.package.identifier,
                attribution=installed.tile.package.attribution,
                online_refresh_allowed=False,
            )

        online_refresh_allowed = installed.covering_package is None

        cached = self._cache.read(key)
        if cached is None:
            return ResolvedMapTile(
                png=None,
                source=MapTileSource.MISSING,
                online_refresh_allowed=online_refresh_allowed,
            )

        return ResolvedMapTile(
            png=cached.png,
            source=(MapTileSource.CACHE if cached.is_fresh else MapTileSource.STALE_CACHE),
            attribution=self._online_attribution,
            online_refresh_allowed=online_refresh_allowed,
        )

    def refresh_online(
        self,
        key: MapTileKey,
        fallback: ResolvedMapTile,
    ) -> ResolvedMapTile:
        """Refresh from the network while preserving local fallback data."""
        if not fallback.online_refresh_allowed:
            return fallback

        try:
            png = self._online.fetch(key)
            self._cache.write(key, png)
            return ResolvedMapTile(
                png=png,
                source=MapTileSource.NETWORK,
                attribution=self._online_attribution,
            )
        except MapTileError:
            return fallback

    def close(self) -> None:
        """Release installed-package resources."""
        self._installed.close()
