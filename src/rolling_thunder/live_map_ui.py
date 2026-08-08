"""Tkinter adapter for immutable live-map presentation and tile snapshots."""

from __future__ import annotations

from base64 import b64encode
from collections import OrderedDict
from dataclasses import dataclass
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
from rolling_thunder.map_sources import DEFAULT_MAP_ATTRIBUTION
from rolling_thunder.map_tiles import MapTileKey

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
        lines.append(f"{presentation.position.latitude:.5f}, {presentation.position.longitude:.5f}")
    return tuple(lines)


def live_map_health_color(level: LiveMapHealthLevel) -> str:
    """Return the approved light-blue/yellow/gray subsystem health color."""
    if level is LiveMapHealthLevel.HEALTHY:
        return _HEALTHY
    if level is LiveMapHealthLevel.DEGRADED:
        return _WARNING
    return _MUTED


def live_map_info_lines(info: LiveMapInfoPresentation) -> tuple[str, ...]:
    """Build the compact information-box lines from immutable presentation state."""
    return (
        f"LOCAL  {info.local_time}",
        f"UTC    {info.utc_time}",
        f"GRID   {info.grid}",
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

    previous_keys = set(previous_tiles)
    current_keys = set(current_tiles)

    remove = tuple(sorted(previous_keys - current_keys))
    redraw = tuple(
        sorted(
            key
            for key in current_keys
            if (key not in previous_tiles or previous_tiles[key].png != current_tiles[key].png)
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

    return TileUpdatePlan(
        remove=remove,
        redraw=redraw,
        move=move,
    )


def _snapshot_tiles_by_key(
    snapshot: LiveMapSnapshot | None,
) -> dict[MapTileKey, MapTileSnapshot]:
    if snapshot is None:
        return {}
    return {tile.placement.key: tile for tile in snapshot.tiles}


class LiveMapWidgets:
    """Render live map snapshots without performing tile, cache, or GPS I/O."""

    def __init__(self, parent: Any) -> None:
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
        self._attribution_item: int | None = None

        self._last_snapshot: LiveMapSnapshot | None = None
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
    ) -> None:
        """Update changed map tiles and redraw lightweight overlays."""
        width, height = self.viewport_size
        size = (width, height)
        snapshot_changed = snapshot is not self._last_snapshot
        size_changed = size != self._last_size

        if size_changed:
            self._draw_base(snapshot, width, height)
        elif snapshot_changed:
            self._update_base(self._last_snapshot, snapshot, width, height)

        self._last_snapshot = snapshot
        self._last_size = size

        self._canvas.delete("map-overlay")
        if presentation.position is not None:
            self._draw_vehicle_marker(
                width / 2,
                height / 2,
                presentation.is_current,
                presentation.heading_degrees or 0.0,
            )
        self._draw_status(presentation, snapshot)

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
            text=(snapshot.attribution if snapshot is not None else DEFAULT_MAP_ATTRIBUTION),
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

        # Draw wheels first so the larger top-down car remains readable over
        # detailed map tiles.
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
    ) -> None:
        info = self._info_controller.update(presentation, snapshot)
        lines = live_map_info_lines(info)
        canvas = self._canvas
        width = max(900, canvas.winfo_width())

        canvas.create_rectangle(
            12,
            12,
            430,
            174,
            fill=_STATUS_BACKGROUND,
            outline=_MUTED,
            width=3,
            tags="map-overlay",
        )
        canvas.create_text(
            30,
            26,
            text="\n".join(lines),
            fill=_MARKER_OUTLINE,
            font=("DejaVu Sans Mono", 26, "bold"),
            anchor="nw",
            justify="left",
            tags="map-overlay",
        )

        health_right = width - 12
        health_left = health_right - 420
        canvas.create_rectangle(
            health_left,
            12,
            health_right,
            156,
            fill=_STATUS_BACKGROUND,
            outline=_MUTED,
            width=3,
            tags="map-overlay",
        )

        self._draw_health_line(
            "MAP",
            info.map_health.level,
            info.map_health.detail,
            health_left + 22,
            34,
        )
        self._draw_health_line(
            "GPS",
            info.gps_health.level,
            info.gps_health.detail,
            health_left + 22,
            94,
        )

    def _draw_health_line(
        self,
        name: str,
        level: LiveMapHealthLevel,
        detail: str,
        x: int,
        y: int,
    ) -> None:
        color = live_map_health_color(level)
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
            text=f"{name}  {detail}",
            fill=color,
            font=("DejaVu Sans", 25, "bold"),
            anchor="nw",
            justify="left",
            tags="map-overlay",
        )
