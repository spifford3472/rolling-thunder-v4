"""Raster-map tile math, HTTP retrieval, validation, and disk caching."""

from __future__ import annotations

import math
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.error import URLError

from PIL import Image, UnidentifiedImageError

from rolling_thunder.http_home_platform import HttpTransport, UrllibHttpTransport
from rolling_thunder.live_map import GeoPoint

TILE_SIZE_PX = 256
MAX_WEB_MERCATOR_LATITUDE = 85.05112878
DEFAULT_MAP_USER_AGENT = (
    "RollingThunder-v4/4.1 "
    "(amateur-radio mobile dashboard; "
    "https://github.com/spifford3472/rolling-thunder-v4)"
)
DEFAULT_MAP_CACHE_PRUNE_INTERVAL_WRITES = 64
_MAX_TILE_BYTES = 2_000_000


class MapTileError(RuntimeError):
    """Raised when one raster map tile cannot be safely retrieved or decoded."""


@dataclass(frozen=True, order=True)
class MapTileKey:
    """One normalized slippy-map tile coordinate."""

    zoom: int
    x: int
    y: int

    def __post_init__(self) -> None:
        if not 0 <= self.zoom <= 22:
            raise ValueError("Map tile zoom must be between 0 and 22.")
        limit = 1 << self.zoom
        if not 0 <= self.x < limit:
            raise ValueError("Map tile x coordinate is outside the zoom range.")
        if not 0 <= self.y < limit:
            raise ValueError("Map tile y coordinate is outside the zoom range.")


@dataclass(frozen=True)
class MapTilePlacement:
    """One tile and its top-left viewport pixel."""

    key: MapTileKey
    x_px: int
    y_px: int


@dataclass(frozen=True)
class MapViewport:
    """Immutable visible tile layout around one geographic center."""

    center: GeoPoint
    zoom: int
    width_px: int
    height_px: int
    placements: tuple[MapTilePlacement, ...]

    @property
    def tile_keys(self) -> tuple[MapTileKey, ...]:
        """Return unique tile keys in deterministic order."""
        return tuple(sorted({placement.key for placement in self.placements}))


@dataclass(frozen=True)
class CachedMapTile:
    """Validated cached tile bytes and freshness metadata."""

    png: bytes
    stored_at: datetime
    is_fresh: bool


def web_mercator_world_pixel(
    point: GeoPoint,
    zoom: int,
) -> tuple[float, float]:
    """Convert latitude/longitude to world pixels at one slippy-map zoom."""
    if not 0 <= zoom <= 22:
        raise ValueError("Map zoom must be between 0 and 22.")

    latitude = max(
        -MAX_WEB_MERCATOR_LATITUDE,
        min(MAX_WEB_MERCATOR_LATITUDE, point.latitude),
    )
    world_size = TILE_SIZE_PX * (1 << zoom)
    x = (point.longitude + 180.0) / 360.0 * world_size
    latitude_radians = math.radians(latitude)
    y = (
        1.0 - math.asinh(math.tan(latitude_radians)) / math.pi
    ) / 2.0 * world_size
    return x, y


def build_map_viewport(
    center: GeoPoint,
    *,
    zoom: int,
    width_px: int,
    height_px: int,
) -> MapViewport:
    """Build all visible tile placements for a centered north-up viewport."""
    if width_px < 1 or height_px < 1:
        raise ValueError("Map viewport dimensions must be positive.")

    center_x, center_y = web_mercator_world_pixel(center, zoom)
    left = center_x - width_px / 2.0
    top = center_y - height_px / 2.0
    first_tile_x = math.floor(left / TILE_SIZE_PX)
    last_tile_x = math.floor((left + width_px - 1) / TILE_SIZE_PX)
    first_tile_y = math.floor(top / TILE_SIZE_PX)
    last_tile_y = math.floor((top + height_px - 1) / TILE_SIZE_PX)
    tile_limit = 1 << zoom

    placements: list[MapTilePlacement] = []
    for display_y in range(first_tile_y, last_tile_y + 1):
        if not 0 <= display_y < tile_limit:
            continue
        for display_x in range(first_tile_x, last_tile_x + 1):
            wrapped_x = display_x % tile_limit
            placements.append(
                MapTilePlacement(
                    key=MapTileKey(zoom=zoom, x=wrapped_x, y=display_y),
                    x_px=round(display_x * TILE_SIZE_PX - left),
                    y_px=round(display_y * TILE_SIZE_PX - top),
                )
            )

    return MapViewport(
        center=center,
        zoom=zoom,
        width_px=width_px,
        height_px=height_px,
        placements=tuple(placements),
    )


def validate_map_tile_png(
    body: bytes,
    *,
    maximum_bytes: int = _MAX_TILE_BYTES,
) -> bytes:
    """Validate bounded 256x256 PNG bytes and return an immutable copy."""
    if not body:
        raise MapTileError("Map tile response was empty.")
    if len(body) > maximum_bytes:
        raise MapTileError("Map tile response exceeded the safe size limit.")

    try:
        with Image.open(BytesIO(body)) as image:
            image.verify()
        with Image.open(BytesIO(body)) as image:
            if image.format != "PNG":
                raise MapTileError("Map tile response was not a PNG image.")
            if image.size != (TILE_SIZE_PX, TILE_SIZE_PX):
                raise MapTileError("Map tile response was not 256 by 256 pixels.")
    except (UnidentifiedImageError, OSError, SyntaxError) as error:
        raise MapTileError("Map tile response contained an invalid image.") from error
    return bytes(body)


class MapTileClient:
    """Retrieve one visible map tile through the injectable HTTP boundary."""

    def __init__(
        self,
        url_template: str,
        *,
        timeout_s: float = 4.0,
        transport: HttpTransport | None = None,
        user_agent: str = DEFAULT_MAP_USER_AGENT,
    ) -> None:
        if timeout_s <= 0:
            raise ValueError("Map tile HTTP timeout must be positive.")
        if not user_agent.strip():
            raise ValueError("Map tile user agent must not be blank.")
        for token in ("{z}", "{x}", "{y}"):
            if token not in url_template:
                raise ValueError(f"Map tile URL template must contain {token}.")
        self._url_template = url_template
        self._timeout_s = timeout_s
        self._transport = transport or UrllibHttpTransport()
        self._user_agent = user_agent.strip()

    def fetch(self, key: MapTileKey) -> bytes:
        """Fetch and validate one tile or raise a stable map-data error."""
        url = self._url_template.format(z=key.zoom, x=key.x, y=key.y)
        try:
            response = self._transport.request(
                "GET",
                url,
                headers={
                    "Accept": "image/png",
                    "User-Agent": self._user_agent,
                },
                body=None,
                timeout_s=self._timeout_s,
            )
        except (TimeoutError, URLError, OSError) as error:
            raise MapTileError(f"Map tile request failed: {error}") from error

        if not 200 <= response.status_code < 300:
            raise MapTileError(
                f"Map tile request returned HTTP {response.status_code}."
            )
        return validate_map_tile_png(response.body)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class MapTileCache:
    """Bounded validated raster-tile cache with amortized pruning."""

    def __init__(
        self,
        root: Path,
        *,
        retention: timedelta = timedelta(days=7),
        maximum_tiles: int = 2_048,
        prune_interval_writes: int = DEFAULT_MAP_CACHE_PRUNE_INTERVAL_WRITES,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if retention < timedelta(days=7):
            raise ValueError("Map tile cache retention must be at least seven days.")
        if maximum_tiles < 1:
            raise ValueError("Map tile cache size must be positive.")
        if prune_interval_writes < 1:
            raise ValueError("Map tile cache prune interval must be positive.")
        self._root = root
        self._retention = retention
        self._maximum_tiles = maximum_tiles
        self._prune_interval_writes = prune_interval_writes
        self._writes_since_prune = prune_interval_writes - 1
        self._clock = clock

    def read(self, key: MapTileKey) -> CachedMapTile | None:
        """Read and validate one cached tile without contacting the network."""
        path = self._path_for(key)
        try:
            body = path.read_bytes()
            stat = path.stat()
        except FileNotFoundError:
            return None
        except OSError:
            return None

        try:
            png = validate_map_tile_png(body)
        except MapTileError:
            try:
                path.unlink()
            except OSError:
                pass
            return None

        stored_at = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
        now = self._aware_now()
        return CachedMapTile(
            png=png,
            stored_at=stored_at,
            is_fresh=(now - stored_at) <= self._retention,
        )

    def write(self, key: MapTileKey, png: bytes) -> None:
        """Atomically persist one validated tile and prune on a bounded cadence."""
        validated = validate_map_tile_png(png)
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)

        temporary_path: Path | None = None
        try:
            with NamedTemporaryFile(
                mode="wb",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary.write(validated)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = Path(temporary.name)
            os.replace(temporary_path, path)
            timestamp = self._aware_now().timestamp()
            os.utime(path, (timestamp, timestamp))
        finally:
            if temporary_path is not None and temporary_path.exists():
                try:
                    temporary_path.unlink()
                except OSError:
                    pass

        self._writes_since_prune += 1
        if self._writes_since_prune >= self._prune_interval_writes:
            self._prune()
            self._writes_since_prune = 0

    def _prune(self) -> None:
        try:
            entries = sorted(
                (
                    (path.stat().st_mtime, path)
                    for path in self._root.glob("*/*/*.png")
                    if path.is_file()
                ),
                key=lambda item: item[0],
            )
        except OSError:
            return

        excess = len(entries) - self._maximum_tiles
        for _, path in entries[: max(0, excess)]:
            try:
                path.unlink()
            except OSError:
                continue

    def _path_for(self, key: MapTileKey) -> Path:
        return self._root / str(key.zoom) / str(key.x) / f"{key.y}.png"

    def _aware_now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Map tile cache clock must return aware timestamps.")
        return now.astimezone(UTC)
