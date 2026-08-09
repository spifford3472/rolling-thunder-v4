"""Web Mercator geometry and alpha processing for radar overlay tiles."""

from __future__ import annotations

from io import BytesIO

from PIL import Image, UnidentifiedImageError

from rolling_thunder.map_tiles import MapTileError, MapTileKey, validate_map_tile_png

_WEB_MERCATOR_HALF_WORLD_M = 20_037_508.342789244


def web_mercator_tile_bounds(key: MapTileKey) -> tuple[float, float, float, float]:
    """Return one slippy tile bbox as EPSG:3857 xmin,ymin,xmax,ymax metres."""
    tile_span = (2.0 * _WEB_MERCATOR_HALF_WORLD_M) / (1 << key.zoom)
    xmin = -_WEB_MERCATOR_HALF_WORLD_M + key.x * tile_span
    xmax = xmin + tile_span
    ymax = _WEB_MERCATOR_HALF_WORLD_M - key.y * tile_span
    ymin = ymax - tile_span
    return xmin, ymin, xmax, ymax


def apply_radar_opacity(png: bytes, opacity: float = 0.55) -> bytes:
    """Return a validated 256x256 radar PNG with its alpha scaled outside Tkinter."""
    if not 0.0 < opacity <= 1.0:
        raise ValueError("Radar opacity must be greater than zero and at most one.")
    validated = validate_map_tile_png(png)
    try:
        with Image.open(BytesIO(validated)) as source:
            image = source.convert("RGBA")
    except (UnidentifiedImageError, OSError, SyntaxError) as error:
        raise MapTileError("Radar tile contained an invalid image.") from error

    red, green, blue, alpha = image.split()
    alpha = alpha.point(lambda value: round(value * opacity))
    image = Image.merge("RGBA", (red, green, blue, alpha))

    output = BytesIO()
    image.save(output, format="PNG", optimize=False)
    return validate_map_tile_png(output.getvalue())
