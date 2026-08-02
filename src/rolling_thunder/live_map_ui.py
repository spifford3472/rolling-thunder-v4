"""Tkinter adapter for immutable live-map presentation and tile snapshots."""

from __future__ import annotations

from base64 import b64encode
from typing import Any

from rolling_thunder.live_map import LiveMapGpsStatus, LiveMapPresentation
from rolling_thunder.live_map_service import LiveMapSnapshot, MapDataStatus

_BACKGROUND = "#0d1418"
_MISSING_TILE = "#17242a"
_GRID_LINE = "#26363d"
_BRIGHT = "#ffffff"
_MUTED = "#a8b4ba"
_READY = "#42ff72"
_WARNING = "#ffd24a"
_FAILURE = "#ff7070"
_MARKER = "#ff4040"
_MARKER_OUTLINE = "#ffffff"
_STATUS_BACKGROUND = "#10191e"
_ATTRIBUTION_BACKGROUND = "#10191e"


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
        lines.append(
            f"{presentation.position.latitude:.5f}, "
            f"{presentation.position.longitude:.5f}"
        )
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
        """Redraw the current immutable map state."""
        canvas = self._canvas
        width, height = self.viewport_size
        canvas.delete("live-map")
        self._tile_photos.clear()
        canvas.create_rectangle(
            0,
            0,
            width,
            height,
            fill=_BACKGROUND,
            outline="",
            tags="live-map",
        )

        if snapshot is not None and snapshot.viewport is not None:
            self._draw_tiles(snapshot)
        else:
            self._draw_reference_grid(width, height)

        if presentation.position is not None:
            self._draw_vehicle_marker(width / 2, height / 2, presentation.is_current)

        self._draw_status(presentation, snapshot)
        canvas.create_text(
            width - 12,
            height - 10,
            text="© OpenStreetMap contributors",
            fill=_MUTED,
            font=("DejaVu Sans", 11, "bold"),
            anchor="se",
            tags="live-map",
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
                    tags="live-map",
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
                tags="live-map",
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
                tags="live-map",
            )
        for y in range(0, height + spacing, spacing):
            canvas.create_line(
                0,
                y,
                width,
                y,
                fill=_GRID_LINE,
                tags="live-map",
            )

    def _draw_vehicle_marker(
        self,
        center_x: float,
        center_y: float,
        is_current: bool,
    ) -> None:
        fill = _MARKER if is_current else _WARNING
        radius = 15
        self._canvas.create_oval(
            center_x - radius,
            center_y - radius,
            center_x + radius,
            center_y + radius,
            fill=fill,
            outline=_MARKER_OUTLINE,
            width=4,
            tags="live-map",
        )
        self._canvas.create_oval(
            center_x - 4,
            center_y - 4,
            center_x + 4,
            center_y + 4,
            fill=_MARKER_OUTLINE,
            outline="",
            tags="live-map",
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
            500,
            34 + len(lines) * 28,
            fill=_STATUS_BACKGROUND,
            outline=color,
            width=2,
            tags="live-map",
        )
        self._canvas.create_text(
            28,
            24,
            text=text,
            fill=color,
            font=("DejaVu Sans", 17, "bold"),
            anchor="nw",
            justify="left",
            tags="live-map",
        )
