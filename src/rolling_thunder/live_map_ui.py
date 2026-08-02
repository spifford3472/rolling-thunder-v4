"""Tkinter adapter for immutable live-map presentation and tile snapshots."""

from __future__ import annotations

from base64 import b64encode
from math import cos, radians, sin
from typing import Any

from rolling_thunder.live_map import LiveMapGpsStatus, LiveMapPresentation
from rolling_thunder.live_map_service import LiveMapSnapshot, MapDataStatus

_BACKGROUND = "#0d1418"
_MISSING_TILE = "#17242a"
_GRID_LINE = "#26363d"
_MUTED = "#a8b4ba"
_READY = "#42ff72"
_WARNING = "#ffd24a"
_FAILURE = "#ff7070"
_MARKER = "#ff4040"
_MARKER_OUTLINE = "#ffffff"
_STATUS_BACKGROUND = "#10191e"


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
    """Return a stable status color for the combined GPS and map condition."""
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
    """Build compact operator-facing map status lines."""
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
        self._tile_photos: list[Any] = []
        self._last_snapshot: LiveMapSnapshot | None = None
        self._last_size = (0, 0)

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
        """Redraw changed base-map data and lightweight current overlays."""
        width, height = self.viewport_size
        size = (width, height)
        if snapshot is not self._last_snapshot or size != self._last_size:
            self._draw_base(snapshot, width, height)
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
        self._tile_photos.clear()
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

        canvas.create_text(
            width - 12,
            height - 10,
            text="© OpenStreetMap contributors",
            fill=_MUTED,
            font=("DejaVu Sans", 11, "bold"),
            anchor="se",
            tags="map-base",
        )

    def _draw_tiles(self, snapshot: LiveMapSnapshot) -> None:
        canvas = self._canvas
        for tile in snapshot.tiles:
            placement = tile.placement
            if tile.png is None:
                canvas.create_rectangle(
                    placement.x_px,
                    placement.y_px,
                    placement.x_px + 256,
                    placement.y_px + 256,
                    fill=_MISSING_TILE,
                    outline=_GRID_LINE,
                    tags="map-base",
                )
                continue

            photo = self._tk.PhotoImage(
                data=b64encode(tile.png).decode("ascii"),
            )
            self._tile_photos.append(photo)
            canvas.create_image(
                placement.x_px,
                placement.y_px,
                image=photo,
                anchor="nw",
                tags="map-base",
            )

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
        map_status = snapshot.status if snapshot is not None else None
        lines = live_map_status_lines(presentation, snapshot)
        text = "\n".join(lines)
        color = live_map_status_color(presentation.status, map_status)
        self._canvas.create_rectangle(
            12,
            12,
            880,
            54 + len(lines) * 52,
            fill=_STATUS_BACKGROUND,
            outline=color,
            width=3,
            tags="map-overlay",
        )
        self._canvas.create_text(
            32,
            28,
            text=text,
            fill=color,
            font=("DejaVu Sans", 34, "bold"),
            anchor="nw",
            justify="left",
            tags="map-overlay",
        )
