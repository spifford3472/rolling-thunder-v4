"""Viewport projection and Tk canvas symbols for display-only OHGO markers."""

from __future__ import annotations

from typing import Any

from rolling_thunder.map_tiles import MapViewport, web_mercator_world_pixel
from rolling_thunder.ohgo_layers import OhgoLayer, OhgoLayersSnapshot, OhgoLayerStatus

MARKER_TAG = "map-ohgo"
_MAX_VISIBLE_PER_LAYER = 48
OHGO_MINIMUM_ZOOM = 13
# Match the primary map's north-up car footprint of 60 by 78 pixels.
_MARKER_HALF_WIDTH = 30
_MARKER_HALF_HEIGHT = 39
_CELL_PX = 2 * _MARKER_HALF_HEIGHT
_OUTLINE = "#181818"


def visible_ohgo_markers(
    viewport: MapViewport, layers: OhgoLayersSnapshot
) -> list[tuple[OhgoLayer, float, float]]:
    """Cull points to the visible viewport and thin overlapping same-layer points."""
    if viewport.zoom < OHGO_MINIMUM_ZOOM:
        return []
    center_x, center_y = web_mercator_world_pixel(viewport.center, viewport.zoom)
    size = 256 * (1 << viewport.zoom)
    top = center_y - viewport.height_px / 2
    placements: list[tuple[OhgoLayer, float, float]] = []
    for snapshot in layers:
        if snapshot.status is not OhgoLayerStatus.CURRENT:
            continue
        occupied: set[tuple[int, int]] = set()
        for marker in snapshot.markers:
            world_x = (marker.point.longitude + 180.0) / 360.0 * size
            x = (world_x - center_x + size / 2) % size - size / 2 + viewport.width_px / 2
            if not 0 <= x < viewport.width_px:
                continue
            _, world_y = web_mercator_world_pixel(marker.point, viewport.zoom)
            y = world_y - top
            if not 0 <= y < viewport.height_px:
                continue
            cell = int(x // _CELL_PX), int(y // _CELL_PX)
            if cell in occupied:
                continue
            occupied.add(cell)
            placements.append((snapshot.layer, x, y))
            if len(occupied) >= _MAX_VISIBLE_PER_LAYER:
                break
    return placements


def draw_ohgo_marker(canvas: Any, layer: OhgoLayer, x: float, y: float) -> None:
    """Draw a high-contrast symbol using only Tk canvas primitives."""
    half_width = _MARKER_HALF_WIDTH
    half_height = _MARKER_HALF_HEIGHT
    if layer is OhgoLayer.CONSTRUCTION:
        canvas.create_polygon(
            x - 23, y - half_height, x + 23, y - half_height,
            x + half_width, y + half_height, x - half_width, y + half_height,
            fill="#ff810b", outline=_OUTLINE, width=4, tags=MARKER_TAG,
        )
        for offset in (-14, 14):
            canvas.create_line(
                x - 23, y + offset, x + 23, y + offset,
                fill="#ffffff", width=8, tags=MARKER_TAG,
            )
    elif layer in (OhgoLayer.DANGEROUS_SLOWDOWNS, OhgoLayer.INCIDENTS):
        slowdown = layer is OhgoLayer.DANGEROUS_SLOWDOWNS
        canvas.create_polygon(
            x, y - half_height, x + half_width, y + half_height,
            x - half_width, y + half_height,
            fill="#ffe035" if slowdown else "#ff4747", outline=_OUTLINE, width=4,
            tags=MARKER_TAG,
        )
        canvas.create_text(
            x, y + 17, text="SLOW" if slowdown else "!", fill="#000000",
            font=("DejaVu Sans", -14 if slowdown else -32, "bold"), tags=MARKER_TAG,
        )
    else:
        canvas.create_oval(
            x - half_height, y - half_height, x + half_height, y + half_height,
            fill="#2486e8", outline=_OUTLINE, width=4, tags=MARKER_TAG,
        )
        canvas.create_line(
            x, y - 21, x, y, x + 18, y + 11, fill="#ffffff", width=6, tags=MARKER_TAG,
        )
