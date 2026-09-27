"""Tkinter adapter for immutable live-map presentation and tile snapshots."""

from __future__ import annotations

from base64 import b64encode
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC
from math import cos, radians, sin
from typing import Any

from rolling_thunder.live_map import LiveMapGpsStatus, LiveMapPresentation
from rolling_thunder.live_map_info import (
    LiveMapHealthLevel,
    LiveMapInfoController,
    LiveMapInfoPresentation,
)
from rolling_thunder.live_map_service import (
    LiveMapSnapshot,
    MapDataStatus,
    MapTileSnapshot,
)
from rolling_thunder.live_radar_service import (
    LiveRadarSnapshot,
    RadarDataStatus,
    RadarTileSnapshot,
)
from rolling_thunder.map_sources import DEFAULT_MAP_ATTRIBUTION
from rolling_thunder.map_tiles import MapTileKey
from rolling_thunder.pota_map_markers import (
    PotaMapMarkerSnapshot,
    project_pota_marker,
)
from rolling_thunder.weather_panel import WeatherPanelPresentation

_BACKGROUND = "#0d1418"
_MISSING_TILE = "#17242a"
_GRID_LINE = "#26363d"
_MUTED = "#a8b4ba"
_READY = "#42ff72"
_HEALTHY = "#66ccff"
_WARNING = "#ffd24a"
_FAILURE = "#ff7070"
_MARKER = "#ff4040"
_MARKER_OUTLINE = "#ffffff"
_STATUS_BACKGROUND = "#10191e"
_PHOTO_CACHE_LIMIT = 128
_RADAR_PHOTO_CACHE_LIMIT = 128
_POTA_MARKER_FILL = "#ffd400"
_POTA_MARKER_OUTLINE = "#000000"
_POTA_MARKER_TEXT = "#000000"
_INFO_FONT_SIZE = 40
_INFO_BOX_RIGHT = 680
_INFO_BOX_BOTTOM = 306
_HEALTH_BOX_WIDTH = 460
_STATUS_BOX_GAP = 24


def rotate_marker_points(
    points: tuple[tuple[float, float], ...],
    center_x: float,
    center_y: float,
    heading_degrees: float,
) -> tuple[float, ...]:
    """Rotate marker-local points clockwise using a compass heading."""
    angle = radians(heading_degrees)
    cosine = cos(angle)
    sine = sin(angle)
    rotated: list[float] = []

    for x, y in points:
        rotated.extend(
            (
                center_x + x * cosine - y * sine,
                center_y + x * sine + y * cosine,
            )
        )

    return tuple(rotated)


def live_map_status_color(
    gps_status: LiveMapGpsStatus,
    map_status: MapDataStatus | None,
) -> str:
    """Return the legacy combined status color for pure regression coverage."""
    if gps_status is LiveMapGpsStatus.ERROR:
        return _FAILURE
    if map_status is MapDataStatus.UNAVAILABLE:
        return _FAILURE
    if gps_status in {LiveMapGpsStatus.STALE, LiveMapGpsStatus.LAST_KNOWN}:
        return _WARNING
    if map_status in {MapDataStatus.CACHE_ONLY, MapDataStatus.PARTIAL}:
        return _WARNING
    if gps_status is LiveMapGpsStatus.READY and map_status is MapDataStatus.READY:
        return _READY
    return _MUTED


def live_map_status_lines(
    presentation: LiveMapPresentation,
    snapshot: LiveMapSnapshot | None,
) -> tuple[str, ...]:
    """Build the legacy compact status lines for pure regression coverage."""
    lines = [presentation.detail]
    if snapshot is None:
        lines.append("MAP DISABLED")
    else:
        lines.append(snapshot.detail)

    if presentation.grid is not None:
        lines.append(f"GRID {presentation.grid.upper()}")
    if presentation.position is not None:
        lines.append(
            f"{presentation.position.latitude:.5f}, "
            f"{presentation.position.longitude:.5f}"
        )
    return tuple(lines)


def live_map_health_color(level: LiveMapHealthLevel) -> str:
    """Return the approved light-blue/yellow/gray subsystem health color."""
    if level is LiveMapHealthLevel.HEALTHY:
        return _HEALTHY
    if level is LiveMapHealthLevel.DEGRADED:
        return _WARNING
    return _MUTED


def radar_status_color(status: RadarDataStatus | None) -> str:
    """Return the approved blue/yellow/gray/red radar health color."""
    if status is RadarDataStatus.READY:
        return _HEALTHY
    if status in {
        RadarDataStatus.IDLE,
        RadarDataStatus.LOADING,
        RadarDataStatus.STALE,
        RadarDataStatus.PARTIAL,
    }:
        return _WARNING
    if status is RadarDataStatus.UNAVAILABLE:
        return _FAILURE
    return _MUTED


def live_map_info_lines(info: LiveMapInfoPresentation) -> tuple[str, ...]:
    """Build the compact information-box lines from immutable presentation state."""
    return (
        f"LOCAL  {info.local_time}",
        f"UTC    {info.utc_time}",
        f"GRID   {info.grid}",
        f"TEMP   {info.temperature_f} / {info.temperature_c}",
    )


@dataclass(frozen=True)
class TileUpdatePlan:
    """Describe the minimum canvas work between two map snapshots."""

    remove: tuple[MapTileKey, ...]
    redraw: tuple[MapTileKey, ...]
    move: tuple[MapTileKey, ...]


def plan_tile_updates(
    previous: LiveMapSnapshot | None,
    current: LiveMapSnapshot | None,
) -> TileUpdatePlan:
    """Return tile removals, content redraws, and placement-only moves."""
    previous_tiles = _snapshot_tiles_by_key(previous)
    current_tiles = _snapshot_tiles_by_key(current)
    return _plan_snapshot_tile_updates(previous_tiles, current_tiles)


def plan_radar_tile_updates(
    previous: LiveRadarSnapshot | None,
    current: LiveRadarSnapshot | None,
) -> TileUpdatePlan:
    """Return minimum radar canvas work, redrawing all visible tiles on frame swap."""
    previous_tiles = _radar_snapshot_tiles_by_key(previous)
    current_tiles = _radar_snapshot_tiles_by_key(current)
    previous_token = (
        previous.frame.frame_token
        if previous is not None and previous.frame is not None
        else None
    )
    current_token = (
        current.frame.frame_token
        if current is not None and current.frame is not None
        else None
    )
    if previous_token != current_token:
        return TileUpdatePlan(
            remove=tuple(sorted(previous_tiles)),
            redraw=tuple(sorted(current_tiles)),
            move=(),
        )
    return _plan_snapshot_tile_updates(previous_tiles, current_tiles)


def _plan_snapshot_tile_updates(
    previous_tiles: Mapping[MapTileKey, MapTileSnapshot | RadarTileSnapshot],
    current_tiles: Mapping[MapTileKey, MapTileSnapshot | RadarTileSnapshot],
) -> TileUpdatePlan:
    previous_keys = set(previous_tiles)
    current_keys = set(current_tiles)
    remove = tuple(sorted(previous_keys - current_keys))
    redraw = tuple(
        sorted(
            key
            for key in current_keys
            if (
                key not in previous_tiles
                or previous_tiles[key].png != current_tiles[key].png
            )
        )
    )
    move = tuple(
        sorted(
            key
            for key in previous_keys & current_keys
            if (
                previous_tiles[key].png == current_tiles[key].png
                and previous_tiles[key].placement != current_tiles[key].placement
            )
        )
    )
    return TileUpdatePlan(remove=remove, redraw=redraw, move=move)


def _snapshot_tiles_by_key(
    snapshot: LiveMapSnapshot | None,
) -> dict[MapTileKey, MapTileSnapshot]:
    if snapshot is None:
        return {}
    return {tile.placement.key: tile for tile in snapshot.tiles}


def _radar_snapshot_tiles_by_key(
    snapshot: LiveRadarSnapshot | None,
) -> dict[MapTileKey, RadarTileSnapshot]:
    if snapshot is None:
        return {}
    return {tile.placement.key: tile for tile in snapshot.tiles}


def radar_matches_map(
    radar: LiveRadarSnapshot | None,
    map_snapshot: LiveMapSnapshot | None,
) -> bool:
    """Render radar only when its visible placement snapshot matches the map."""
    if radar is None or radar.viewport is None:
        return False
    if map_snapshot is None or map_snapshot.viewport is None:
        return False
    return radar.viewport == map_snapshot.viewport


class LiveMapWidgets:
    """Render live map snapshots without performing tile, cache, radar, GPS, or weather I/O."""

    def __init__(self, parent: Any, *, pota_label_min_zoom: int = 14, pota_dot_diameter_px: int = 12) -> None:
        import tkinter as tk

        self._tk = tk
        self._canvas = tk.Canvas(
            parent,
            bg=_BACKGROUND,
            highlightthickness=0,
        )
        self._canvas.pack(fill="both", expand=True)

        self._tile_items: dict[MapTileKey, int] = {}
        self._tile_item_kinds: dict[MapTileKey, str] = {}
        self._active_photos: dict[MapTileKey, Any] = {}
        self._photo_cache: OrderedDict[
            MapTileKey,
            tuple[bytes, Any],
        ] = OrderedDict()
        self._radar_items: dict[MapTileKey, int] = {}
        self._radar_active_photos: dict[MapTileKey, Any] = {}
        self._radar_photo_cache: OrderedDict[
            tuple[str, MapTileKey],
            tuple[bytes, Any],
        ] = OrderedDict()
        self._attribution_item: int | None = None

        self._last_snapshot: LiveMapSnapshot | None = None
        self._last_radar_snapshot: LiveRadarSnapshot | None = None
        self._last_pota_snapshot: PotaMapMarkerSnapshot | None = None
        self._pota_label_min_zoom = pota_label_min_zoom
        self._pota_dot_diameter_px = pota_dot_diameter_px
        self._last_size = (0, 0)
        self._info_controller = LiveMapInfoController()

    @property
    def viewport_size(self) -> tuple[int, int]:
        """Return the currently allocated viewport dimensions."""
        return (
            max(1, self._canvas.winfo_width()),
            max(1, self._canvas.winfo_height()),
        )

    def update(
        self,
        presentation: LiveMapPresentation,
        snapshot: LiveMapSnapshot | None,
        radar_snapshot: LiveRadarSnapshot | None = None,
        pota_snapshot: PotaMapMarkerSnapshot | None = None,
        weather: WeatherPanelPresentation | None = None,
    ) -> None:
        """Update changed base/radar tiles and redraw lightweight overlays."""
        width, height = self.viewport_size
        size = (width, height)
        snapshot_changed = snapshot is not self._last_snapshot
        radar_changed = radar_snapshot is not self._last_radar_snapshot
        pota_changed = pota_snapshot is not self._last_pota_snapshot
        size_changed = size != self._last_size

        if size_changed:
            self._draw_base(snapshot, width, height)
        elif snapshot_changed:
            self._update_base(self._last_snapshot, snapshot, width, height)

        if size_changed or snapshot_changed or pota_changed:
            self._draw_pota_markers(pota_snapshot, snapshot)

        if size_changed:
            self._draw_radar(radar_snapshot, snapshot)
        elif snapshot_changed or radar_changed or pota_changed:
            self._update_radar(
                self._last_radar_snapshot,
                radar_snapshot,
                snapshot,
            )

        self._last_snapshot = snapshot
        self._last_radar_snapshot = radar_snapshot
        self._last_pota_snapshot = pota_snapshot
        self._last_size = size

        self._canvas.delete("map-overlay")
        if presentation.position is not None:
            self._draw_vehicle_marker(
                width / 2,
                height / 2,
                presentation.is_current,
                presentation.heading_degrees or 0.0,
            )
        self._draw_status(presentation, snapshot, radar_snapshot, weather)

    def _draw_base(
        self,
        snapshot: LiveMapSnapshot | None,
        width: int,
        height: int,
    ) -> None:
        canvas = self._canvas
        canvas.delete("map-base")
        self._tile_items.clear()
        self._tile_item_kinds.clear()
        self._active_photos.clear()
        self._attribution_item = None

        canvas.create_rectangle(
            0,
            0,
            width,
            height,
            fill=_BACKGROUND,
            outline="",
            tags="map-base",
        )

        if snapshot is not None and snapshot.viewport is not None:
            self._draw_tiles(snapshot)
        else:
            self._draw_reference_grid(width, height)

        self._attribution_item = canvas.create_text(
            width - 12,
            height - 10,
            text=(
                snapshot.attribution
                if snapshot is not None
                else DEFAULT_MAP_ATTRIBUTION
            ),
            fill=_MUTED,
            font=("DejaVu Sans", 11, "bold"),
            anchor="se",
            tags="map-base",
        )

    def _update_base(
        self,
        previous: LiveMapSnapshot | None,
        current: LiveMapSnapshot | None,
        width: int,
        height: int,
    ) -> None:
        previous_viewport = previous.viewport if previous is not None else None
        current_viewport = current.viewport if current is not None else None

        if previous_viewport is None or current_viewport is None:
            self._draw_base(current, width, height)
            return

        if previous_viewport.zoom != current_viewport.zoom:
            self._draw_base(current, width, height)
            return

        plan = plan_tile_updates(previous, current)
        current_tiles = _snapshot_tiles_by_key(current)

        for key in plan.remove:
            self._remove_tile(key)

        for key in plan.redraw:
            self._upsert_tile(current_tiles[key])

        for key in plan.move:
            self._move_tile(current_tiles[key])

        if self._attribution_item is not None and current is not None:
            self._canvas.itemconfigure(
                self._attribution_item,
                text=current.attribution,
            )

    def _draw_tiles(self, snapshot: LiveMapSnapshot) -> None:
        for tile in snapshot.tiles:
            self._upsert_tile(tile)

    def _upsert_tile(self, tile: MapTileSnapshot) -> None:
        key = tile.placement.key
        placement = tile.placement
        self._remove_tile(key)

        if tile.png is None:
            item = self._canvas.create_rectangle(
                placement.x_px,
                placement.y_px,
                placement.x_px + 256,
                placement.y_px + 256,
                fill=_MISSING_TILE,
                outline=_GRID_LINE,
                tags="map-base",
            )
            self._tile_item_kinds[key] = "rectangle"
        else:
            photo = self._photo_for_tile(key, tile.png)
            self._active_photos[key] = photo
            item = self._canvas.create_image(
                placement.x_px,
                placement.y_px,
                image=photo,
                anchor="nw",
                tags="map-base",
            )
            self._tile_item_kinds[key] = "image"

        self._tile_items[key] = item
        if self._attribution_item is not None:
            self._canvas.tag_lower(item, self._attribution_item)

        self._trim_photo_cache()

    def _move_tile(self, tile: MapTileSnapshot) -> None:
        key = tile.placement.key
        item = self._tile_items.get(key)
        kind = self._tile_item_kinds.get(key)

        if item is None or kind is None:
            self._upsert_tile(tile)
            return

        placement = tile.placement
        if kind == "image":
            self._canvas.coords(
                item,
                placement.x_px,
                placement.y_px,
            )
        else:
            self._canvas.coords(
                item,
                placement.x_px,
                placement.y_px,
                placement.x_px + 256,
                placement.y_px + 256,
            )

    def _remove_tile(self, key: MapTileKey) -> None:
        item = self._tile_items.pop(key, None)
        if item is not None:
            self._canvas.delete(item)

        self._tile_item_kinds.pop(key, None)
        self._active_photos.pop(key, None)

    def _photo_for_tile(self, key: MapTileKey, png: bytes) -> Any:
        cached = self._photo_cache.get(key)
        if cached is not None and cached[0] == png:
            self._photo_cache.move_to_end(key)
            return cached[1]

        photo = self._tk.PhotoImage(
            data=b64encode(png).decode("ascii"),
        )
        self._photo_cache[key] = (png, photo)
        self._photo_cache.move_to_end(key)
        return photo

    def _trim_photo_cache(self) -> None:
        while len(self._photo_cache) > _PHOTO_CACHE_LIMIT:
            removable = next(
                (key for key in self._photo_cache if key not in self._active_photos),
                None,
            )
            if removable is None:
                return
            self._photo_cache.pop(removable, None)

    def _draw_pota_markers(
        self,
        pota: PotaMapMarkerSnapshot | None,
        map_snapshot: LiveMapSnapshot | None,
    ) -> None:
        """Draw catalog pins above the base map and below weather radar."""
        self._canvas.delete("map-pota")
        if (
            pota is None
            or pota.viewport is None
            or map_snapshot is None
            or map_snapshot.viewport is None
            or pota.viewport != map_snapshot.viewport
        ):
            return

        viewport = pota.viewport
        if viewport.zoom < self._pota_label_min_zoom:
            radius = self._pota_dot_diameter_px / 2.0
            for marker in pota.markers:
                placement = project_pota_marker(marker, viewport)
                self._canvas.create_oval(
                    placement.x_px - radius,
                    placement.y_px - radius,
                    placement.x_px + radius,
                    placement.y_px + radius,
                    fill=_POTA_MARKER_FILL,
                    outline=_POTA_MARKER_OUTLINE,
                    width=2,
                    tags="map-pota",
                )
        else:
            occupied: list[tuple[int, int, int, int]] = []
            for marker in pota.markers:
                placement = project_pota_marker(marker, viewport)
                text_item = self._canvas.create_text(
                    placement.x_px,
                    placement.y_px,
                    text=f"{marker.reference}\n{marker.name}",
                    fill=_POTA_MARKER_TEXT,
                    font=("DejaVu Sans", 14, "bold"),
                    justify="center",
                    anchor="center",
                    tags="map-pota",
                )
                bbox = self._canvas.bbox(text_item)
                if bbox is None:
                    self._canvas.delete(text_item)
                    continue
                padded = (bbox[0] - 7, bbox[1] - 5, bbox[2] + 7, bbox[3] + 5)
                if any(
                    not (
                        padded[2] < other[0]
                        or padded[0] > other[2]
                        or padded[3] < other[1]
                        or padded[1] > other[3]
                    )
                    for other in occupied
                ):
                    self._canvas.delete(text_item)
                    continue
                rectangle = self._canvas.create_rectangle(
                    *padded,
                    fill=_POTA_MARKER_FILL,
                    outline=_POTA_MARKER_OUTLINE,
                    width=2,
                    tags="map-pota",
                )
                self._canvas.tag_lower(rectangle, text_item)
                occupied.append(padded)

        if self._canvas.find_withtag("map-pota"):
            self._canvas.tag_raise("map-pota", "map-base")
        self._raise_radar_layer()

    def _draw_radar(
        self,
        radar: LiveRadarSnapshot | None,
        map_snapshot: LiveMapSnapshot | None,
    ) -> None:
        self._clear_radar()
        if (
            not radar_matches_map(radar, map_snapshot)
            or radar is None
            or radar.frame is None
        ):
            return

        frame_token = radar.frame.frame_token
        for tile in radar.tiles:
            self._upsert_radar_tile(frame_token, tile)
        self._raise_radar_layer()
        self._trim_radar_photo_cache(frame_token)

    def _update_radar(
        self,
        previous: LiveRadarSnapshot | None,
        current: LiveRadarSnapshot | None,
        map_snapshot: LiveMapSnapshot | None,
    ) -> None:
        if (
            not radar_matches_map(current, map_snapshot)
            or current is None
            or current.frame is None
        ):
            self._clear_radar()
            return

        current_viewport = current.viewport
        previous_viewport = previous.viewport if previous is not None else None
        if (
            previous is None
            or previous.frame is None
            or previous_viewport is None
            or current_viewport is None
            or previous_viewport.zoom != current_viewport.zoom
        ):
            self._draw_radar(current, map_snapshot)
            return

        plan = plan_radar_tile_updates(previous, current)
        current_tiles = _radar_snapshot_tiles_by_key(current)
        frame_token = current.frame.frame_token

        for key in plan.remove:
            self._remove_radar_tile(key)
        for key in plan.redraw:
            self._upsert_radar_tile(frame_token, current_tiles[key])
        for key in plan.move:
            self._move_radar_tile(frame_token, current_tiles[key])

        self._raise_radar_layer()
        self._trim_radar_photo_cache(frame_token)

    def _clear_radar(self) -> None:
        self._canvas.delete("map-radar")
        self._radar_items.clear()
        self._radar_active_photos.clear()

    def _upsert_radar_tile(
        self,
        frame_token: str,
        tile: RadarTileSnapshot,
    ) -> None:
        key = tile.placement.key
        self._remove_radar_tile(key)
        if tile.png is None:
            return
        cache_key = (frame_token, key)
        photo = self._radar_photo_for_tile(cache_key, tile.png)
        self._radar_active_photos[key] = photo
        self._radar_items[key] = self._canvas.create_image(
            tile.placement.x_px,
            tile.placement.y_px,
            image=photo,
            anchor="nw",
            tags="map-radar",
        )

    def _move_radar_tile(
        self,
        frame_token: str,
        tile: RadarTileSnapshot,
    ) -> None:
        key = tile.placement.key
        item = self._radar_items.get(key)
        if item is None:
            self._upsert_radar_tile(frame_token, tile)
            return
        self._canvas.coords(
            item,
            tile.placement.x_px,
            tile.placement.y_px,
        )

    def _remove_radar_tile(self, key: MapTileKey) -> None:
        item = self._radar_items.pop(key, None)
        if item is not None:
            self._canvas.delete(item)
        self._radar_active_photos.pop(key, None)

    def _raise_radar_layer(self) -> None:
        """Keep optional POTA/radar layers ordered without referencing empty tags."""
        pota_items = self._canvas.find_withtag("map-pota")
        radar_items = self._canvas.find_withtag("map-radar")

        if radar_items:
            if pota_items:
                self._canvas.tag_raise("map-radar", "map-pota")
            else:
                self._canvas.tag_raise("map-radar", "map-base")
            if self._attribution_item is not None:
                self._canvas.tag_raise(self._attribution_item, "map-radar")
            return

        if self._attribution_item is not None:
            if pota_items:
                self._canvas.tag_raise(self._attribution_item, "map-pota")
            else:
                self._canvas.tag_raise(self._attribution_item, "map-base")

    def _radar_photo_for_tile(
        self,
        cache_key: tuple[str, MapTileKey],
        png: bytes,
    ) -> Any:
        cached = self._radar_photo_cache.get(cache_key)
        if cached is not None and cached[0] == png:
            self._radar_photo_cache.move_to_end(cache_key)
            return cached[1]
        photo = self._tk.PhotoImage(data=b64encode(png).decode("ascii"))
        self._radar_photo_cache[cache_key] = (png, photo)
        self._radar_photo_cache.move_to_end(cache_key)
        return photo

    def _trim_radar_photo_cache(self, active_frame_token: str) -> None:
        while len(self._radar_photo_cache) > _RADAR_PHOTO_CACHE_LIMIT:
            removable = next(
                (
                    cache_key
                    for cache_key in self._radar_photo_cache
                    if (
                        cache_key[0] != active_frame_token
                        or cache_key[1] not in self._radar_active_photos
                    )
                ),
                None,
            )
            if removable is None:
                return
            self._radar_photo_cache.pop(removable, None)

    def _draw_reference_grid(self, width: int, height: int) -> None:
        canvas = self._canvas
        spacing = 80
        for x in range(0, width + spacing, spacing):
            canvas.create_line(
                x,
                0,
                x,
                height,
                fill=_GRID_LINE,
                tags="map-base",
            )
        for y in range(0, height + spacing, spacing):
            canvas.create_line(
                0,
                y,
                width,
                y,
                fill=_GRID_LINE,
                tags="map-base",
            )

    def _draw_vehicle_marker(
        self,
        center_x: float,
        center_y: float,
        is_current: bool,
        heading_degrees: float,
    ) -> None:
        fill = _MARKER if is_current else _WARNING
        canvas = self._canvas

        def polygon(
            points: tuple[tuple[float, float], ...],
            *,
            polygon_fill: str,
            outline: str,
            width: int,
        ) -> None:
            canvas.create_polygon(
                rotate_marker_points(
                    points,
                    center_x,
                    center_y,
                    heading_degrees,
                ),
                fill=polygon_fill,
                outline=outline,
                width=width,
                joinstyle="round",
                tags="map-overlay",
            )

        for wheel in (
            ((-30.0, -24.0), (-22.0, -24.0), (-22.0, -7.0), (-30.0, -7.0)),
            ((22.0, -24.0), (30.0, -24.0), (30.0, -7.0), (22.0, -7.0)),
            ((-30.0, 9.0), (-22.0, 9.0), (-22.0, 27.0), (-30.0, 27.0)),
            ((22.0, 9.0), (30.0, 9.0), (30.0, 27.0), (22.0, 27.0)),
        ):
            polygon(
                wheel,
                polygon_fill=_STATUS_BACKGROUND,
                outline=_MARKER_OUTLINE,
                width=2,
            )

        polygon(
            (
                (-14.0, -39.0),
                (14.0, -39.0),
                (23.0, -24.0),
                (23.0, 25.0),
                (15.0, 39.0),
                (-15.0, 39.0),
                (-23.0, 25.0),
                (-23.0, -24.0),
            ),
            polygon_fill=fill,
            outline=_MARKER_OUTLINE,
            width=4,
        )

        polygon(
            (
                (-13.0, -22.0),
                (13.0, -22.0),
                (17.0, -6.0),
                (-17.0, -6.0),
            ),
            polygon_fill=_STATUS_BACKGROUND,
            outline=_MARKER_OUTLINE,
            width=2,
        )
        polygon(
            (
                (-17.0, 7.0),
                (17.0, 7.0),
                (12.0, 24.0),
                (-12.0, 24.0),
            ),
            polygon_fill=_STATUS_BACKGROUND,
            outline=_MARKER_OUTLINE,
            width=2,
        )

        for light_x in (-11.0, 11.0):
            polygon(
                (
                    (light_x - 4.0, -34.0),
                    (light_x + 4.0, -34.0),
                    (light_x + 4.0, -27.0),
                    (light_x - 4.0, -27.0),
                ),
                polygon_fill=_MARKER_OUTLINE,
                outline="",
                width=0,
            )

    def _draw_status(
        self,
        presentation: LiveMapPresentation,
        snapshot: LiveMapSnapshot | None,
        radar: LiveRadarSnapshot | None,
        weather: WeatherPanelPresentation | None,
    ) -> None:
        info = self._info_controller.update(presentation, snapshot, weather)
        lines = live_map_info_lines(info)
        canvas = self._canvas
        width = max(900, canvas.winfo_width())

        canvas.create_rectangle(
            12,
            12,
            _INFO_BOX_RIGHT,
            _INFO_BOX_BOTTOM,
            fill=_STATUS_BACKGROUND,
            outline=_MUTED,
            width=3,
            tags="map-overlay",
        )
        canvas.create_text(
            30,
            24,
            text="\n".join(lines),
            fill=_MARKER_OUTLINE,
            font=("DejaVu Sans Mono", _INFO_FONT_SIZE, "bold"),
            anchor="nw",
            justify="left",
            tags="map-overlay",
        )

        health_right = width - 12
        health_left = max(
            _INFO_BOX_RIGHT + _STATUS_BOX_GAP,
            health_right - _HEALTH_BOX_WIDTH,
        )
        canvas.create_rectangle(
            health_left,
            12,
            health_right,
            216,
            fill=_STATUS_BACKGROUND,
            outline=_MUTED,
            width=3,
            tags="map-overlay",
        )

        self._draw_health_line(
            "MAP",
            live_map_health_color(info.map_health.level),
            info.map_health.detail,
            health_left + 22,
            34,
        )
        self._draw_health_line(
            "GPS",
            live_map_health_color(info.gps_health.level),
            info.gps_health.detail,
            health_left + 22,
            94,
        )
        self._draw_health_line(
            "RADAR",
            radar_status_color(radar.status if radar is not None else None),
            "",
            health_left + 22,
            154,
        )

        if radar is not None and radar.attribution is not None:
            observed = (
                radar.frame.observed_at.astimezone(UTC).strftime("%H:%MZ")
                if radar.frame is not None
                else "--:--Z"
            )
            canvas.create_text(
                12,
                max(230, canvas.winfo_height() - 10),
                text=f"{radar.attribution} • OBS {observed}",
                fill=_MUTED,
                font=("DejaVu Sans", 11, "bold"),
                anchor="sw",
                tags="map-overlay",
            )

    def _draw_health_line(
        self,
        name: str,
        color: str,
        detail: str,
        x: int,
        y: int,
    ) -> None:
        self._canvas.create_oval(
            x,
            y + 4,
            x + 24,
            y + 28,
            fill=color,
            outline=color,
            tags="map-overlay",
        )
        self._canvas.create_text(
            x + 38,
            y,
            text=name if not detail else f"{name}  {detail}",
            fill=color,
            font=("DejaVu Sans", 25, "bold"),
            anchor="nw",
            justify="left",
            tags="map-overlay",
        )
