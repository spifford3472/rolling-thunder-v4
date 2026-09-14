"""Local-first raster-map package discovery and tile resolution."""

from __future__ import annotations

import math
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from threading import Lock
from time import monotonic
from typing import Protocol

from rolling_thunder.live_map import GeoPoint
from rolling_thunder.map_refresh import (
    DeferredMapRefreshWorker,
    MapRefreshCoordinator,
    MapRefreshKey,
    MapRefreshReason,
    MapRefreshStorageError,
    MapRefreshStore,
)
from rolling_thunder.map_tiles import (
    CachedMapTile,
    MapTileCache,
    MapTileClient,
    MapTileError,
    MapTileKey,
    tile_key_for_point,
    validate_map_tile_png,
)

DEFAULT_MAP_ATTRIBUTION = "© OpenStreetMap contributors"

_WEB_MERCATOR_LATITUDE_LIMIT = 85.05112878
_GPS_REFRESH_EVALUATION_INTERVAL_S = 300.0


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
    row = math.floor(
        (1.0 - math.asinh(math.tan(latitude_radians)) / math.pi)
        / 2.0
        * tile_count
    )
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
    refreshed_at: datetime

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
    """One tile returned by an installed package or its mutable refresh overlay."""

    png: bytes
    package: InstalledMapMetadata
    refreshed_at: datetime


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
    refreshed_at: datetime | None = None
    refresh_key: MapRefreshKey | None = None


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
                raise MapPackageError(
                    f"Installed map package is closed: {self._path}"
                )
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
            rows = self._connection.execute(
                "SELECT name, value FROM metadata"
            ).fetchall()
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
            raise MapPackageError(
                f"Installed map package minzoom exceeds maxzoom: {self._path}"
            )

        bounds = self._parse_bounds(self._required(metadata, "bounds"))
        attribution = self._required(metadata, "attribution")
        version = self._required(metadata, "version")
        identifier = metadata.get("rolling_thunder_id", self._path.stem).strip()
        if not identifier:
            raise MapPackageError(
                f"Installed map package identifier is blank: {self._path}"
            )

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

        refreshed_at = self._parse_refreshed_at(
            metadata.get("rolling_thunder_refreshed_at")
        )
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
            refreshed_at=refreshed_at,
        )

    def _required(self, metadata: dict[str, str], key: str) -> str:
        value = metadata.get(key, "").strip()
        if not value:
            raise MapPackageError(
                f"Installed map package metadata is missing {key!r}: {self._path}"
            )
        return value

    def _parse_zoom(self, metadata: dict[str, str], key: str) -> int:
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

    def _parse_bounds(self, raw: str) -> tuple[float, float, float, float]:
        try:
            west, south, east, north = (
                float(part.strip()) for part in raw.split(",")
            )
        except (TypeError, ValueError) as error:
            raise MapPackageError(
                "Installed map package bounds must contain "
                f"west,south,east,north: {self._path}"
            ) from error
        if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
            raise MapPackageError(
                f"Installed map package bounds are invalid: {self._path}"
            )
        return west, south, east, north

    def _parse_refreshed_at(self, raw: str | None) -> datetime:
        if raw:
            try:
                value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError as error:
                raise MapPackageError(
                    "Installed map package rolling_thunder_refreshed_at must be "
                    f"an ISO-8601 timestamp: {self._path}"
                ) from error
            if value.tzinfo is None or value.utcoffset() is None:
                raise MapPackageError(
                    "Installed map package refresh timestamp must include a timezone: "
                    f"{self._path}"
                )
            return value.astimezone(UTC)
        try:
            return datetime.fromtimestamp(self._path.stat().st_mtime, tz=UTC)
        except OSError as error:
            raise MapPackageError(
                f"Could not determine installed map package age: {self._path}: {error}"
            ) from error


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
    def load(cls, paths: Iterable[Path]) -> InstalledMapRegistry:
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
        refresh_store: MapRefreshStore | None = None,
    ) -> InstalledMapLookup:
        """Resolve a tile while retaining declared package coverage."""
        with self._lock:
            if self._closed:
                return InstalledMapLookup(tile=None, covering_package=None)
            packages = self._packages

        covering_package: InstalledMapMetadata | None = None
        for package in packages:
            metadata = package.metadata
            if metadata.style is not style or not metadata.covers(key):
                continue
            if covering_package is None:
                covering_package = metadata

            if refresh_store is not None:
                refresh_key = MapRefreshKey(
                    package_id=metadata.identifier,
                    style=metadata.style.value,
                    tile=key,
                )
                try:
                    override = refresh_store.read_override(refresh_key)
                except MapRefreshStorageError as error:
                    with self._lock:
                        self._errors.append(str(error))
                    override = None
                if override is not None:
                    return InstalledMapLookup(
                        tile=InstalledMapTile(
                            png=override.png,
                            package=metadata,
                            refreshed_at=override.refreshed_at,
                        ),
                        covering_package=metadata,
                    )

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
                        refreshed_at=metadata.refreshed_at,
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
    """Resolve installed, refreshed-overlay, cached, and online raster tiles."""

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
        self._refresh_store: MapRefreshStore | None = None
        self._refresh_coordinator: MapRefreshCoordinator | None = None
        self._refresh_worker: DeferredMapRefreshWorker | None = None
        self._gps_refresh_lock = Lock()
        self._last_gps_anchor: MapTileKey | None = None
        self._last_gps_evaluation = 0.0

        if isinstance(online, MapTileClient):
            online.set_style(style.value)
        if (
            isinstance(cache, MapTileCache)
            and isinstance(online, MapTileClient)
            and online.supports_forge_refresh
        ):
            store = MapRefreshStore(cache.refresh_database_path)
            self._refresh_store = store
            self._refresh_coordinator = MapRefreshCoordinator(store)
            self._refresh_worker = DeferredMapRefreshWorker(store, online)

    @property
    def installed_packages(self) -> tuple[InstalledMapMetadata, ...]:
        """Return installed package metadata in lookup order."""
        return self._installed.packages

    @property
    def diagnostics(self) -> tuple[str, ...]:
        """Return non-fatal installed-package failures."""
        return self._installed.errors

    @property
    def style(self) -> MapPackageStyle:
        return self._style

    @property
    def available_styles(self) -> tuple[MapPackageStyle, ...]:
        values = {package.style for package in self._installed.packages}
        return tuple(style for style in MapPackageStyle if style in values)

    @property
    def supported_zoom_levels(self) -> tuple[int, ...]:
        zooms: set[int] = set()
        for package in self._installed.packages:
            if package.style is self._style:
                zooms.update(range(package.min_zoom, package.max_zoom + 1))
        return tuple(sorted(zooms))

    def set_style(self, style: MapPackageStyle) -> bool:
        """Switch presentation style without touching package or network storage."""
        if style is self._style:
            return False
        available = self.available_styles
        if available and style not in available:
            return False
        self._style = style
        if isinstance(self._online, MapTileClient):
            self._online.set_style(style.value)
        with self._gps_refresh_lock:
            self._last_gps_anchor = None
            self._last_gps_evaluation = 0.0
        return True

    def read_local(self, key: MapTileKey) -> ResolvedMapTile:
        """Resolve refreshed/installed package first, then the runtime cache."""
        installed = self._installed.lookup(
            key,
            style=self._style,
            refresh_store=self._refresh_store,
        )
        if installed.tile is not None:
            metadata = installed.tile.package
            return ResolvedMapTile(
                png=installed.tile.png,
                source=MapTileSource.INSTALLED,
                package_id=metadata.identifier,
                attribution=metadata.attribution,
                online_refresh_allowed=False,
                refreshed_at=installed.tile.refreshed_at,
                refresh_key=MapRefreshKey(
                    package_id=metadata.identifier,
                    style=metadata.style.value,
                    tile=key,
                ),
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
            source=(
                MapTileSource.CACHE
                if cached.is_fresh
                else MapTileSource.STALE_CACHE
            ),
            attribution=self._online_attribution,
            online_refresh_allowed=online_refresh_allowed,
            refreshed_at=cached.stored_at,
        )

    def observe_installed_tile(
        self,
        tile: ResolvedMapTile,
        *,
        reason: MapRefreshReason,
    ) -> None:
        """Queue eligible installed tile refresh work without changing rendering."""
        coordinator = self._refresh_coordinator
        if (
            coordinator is None
            or tile.refresh_key is None
            or tile.refreshed_at is None
        ):
            return
        coordinator.observe(
            tile.refresh_key,
            refreshed_at=tile.refreshed_at,
            reason=reason,
        )

    def observe_gps_position(self, point: GeoPoint) -> None:
        """Evaluate the current-position tile at every locally supported zoom."""
        coordinator = self._refresh_coordinator
        zooms = self.supported_zoom_levels
        if coordinator is None or not zooms:
            return
        anchor = tile_key_for_point(point, max(zooms))
        current_monotonic = monotonic()
        with self._gps_refresh_lock:
            if (
                self._last_gps_anchor == anchor
                and current_monotonic - self._last_gps_evaluation
                < _GPS_REFRESH_EVALUATION_INTERVAL_S
            ):
                return
            self._last_gps_anchor = anchor
            self._last_gps_evaluation = current_monotonic

        for zoom in zooms:
            key = tile_key_for_point(point, zoom)
            tile = self.read_local(key)
            self.observe_installed_tile(tile, reason=MapRefreshReason.GPS)

    def refresh_online(
        self,
        key: MapTileKey,
        fallback: ResolvedMapTile,
    ) -> ResolvedMapTile:
        """Refresh ordinary online/cache tiles while preserving local fallback."""
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

    def start_background_refresh(self) -> None:
        worker = self._refresh_worker
        if worker is not None:
            worker.start()

    def stop_background_refresh(self) -> None:
        worker = self._refresh_worker
        if worker is not None:
            worker.stop()

    def close(self) -> None:
        """Release installed-package and refresh-worker resources."""
        self.stop_background_refresh()
        self._installed.close()
