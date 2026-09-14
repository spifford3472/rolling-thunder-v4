#!/usr/bin/env python3
"""Estimate and build Rolling Thunder regional raster MBTiles packages.

The renderer must be a private/local endpoint backed by the extracted Protomaps
vector geography and local styles. This tool intentionally refuses obvious
OpenStreetMap public tile endpoints.
"""

from __future__ import annotations

import argparse
import math
import shutil
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from rolling_thunder.map_tiles import MapTileKey, validate_map_tile_png

PMTILES_IMAGE = (
    "protomaps/go-pmtiles@sha256:"
    "06574f01f55a78f78f887bc7ebf729a5c093c0d6e17d9876300cfcb0758b59d3"
)
DEFAULT_MIN_ZOOM = 6
DEFAULT_MAX_ZOOM = 17
CALIBRATED_BYTES_PER_RASTER_TILE = 10_870
PLANNING_HEADROOM = 1.25


@dataclass(frozen=True, slots=True)
class Region:
    code: str
    name: str
    bounds: tuple[float, float, float, float]


REGIONS = (
    Region("oh", "Ohio", (-84.817996, 38.424267, -80.518598, 41.978802)),
    Region("mi", "Michigan", (-90.415429, 41.694001, -82.413619, 48.173221)),
    Region("in", "Indiana", (-88.060345, 37.788942, -84.801565, 41.759724)),
    Region("ky", "Kentucky", (-89.418626, 36.496384, -81.969987, 39.103408)),
    Region("wv", "West Virginia", (-82.621743, 37.202910, -77.719881, 40.636951)),
    Region("pa", "Pennsylvania", (-80.518598, 39.722302, -74.696610, 42.269079)),
)
REGION_BY_CODE = {region.code: region for region in REGIONS}


def longitude_to_x(longitude: float, zoom: int) -> int:
    limit = 1 << zoom
    return min(max(math.floor((longitude + 180.0) / 360.0 * limit), 0), limit - 1)


def latitude_to_y(latitude: float, zoom: int) -> int:
    limit = 1 << zoom
    clamped = min(max(latitude, -85.05112878), 85.05112878)
    radians = math.radians(clamped)
    row = math.floor((1.0 - math.asinh(math.tan(radians)) / math.pi) / 2.0 * limit)
    return min(max(row, 0), limit - 1)


def tile_rectangle(region: Region, zoom: int) -> tuple[int, int, int, int]:
    west, south, east, north = region.bounds
    return (
        longitude_to_x(west, zoom),
        longitude_to_x(east, zoom),
        latitude_to_y(north, zoom),
        latitude_to_y(south, zoom),
    )


def tile_count(region: Region, min_zoom: int, max_zoom: int) -> int:
    total = 0
    for zoom in range(min_zoom, max_zoom + 1):
        x0, x1, y0, y1 = tile_rectangle(region, zoom)
        total += (x1 - x0 + 1) * (y1 - y0 + 1)
    return total


def regional_tile_count(min_zoom: int, max_zoom: int) -> int:
    return sum(tile_count(region, min_zoom, max_zoom) for region in REGIONS)


def planned_bytes(tiles_per_style: int, styles: int = 2) -> int:
    return math.ceil(
        tiles_per_style
        * styles
        * CALIBRATED_BYTES_PER_RASTER_TILE
        * PLANNING_HEADROOM
    )


def format_gib(value: int) -> str:
    return f"{value / (1024 ** 3):,.1f} GiB"


def command_estimate(args: argparse.Namespace) -> int:
    print("Rolling Thunder six-state raster estimate")
    print(f"minimum zoom: {args.min_zoom}")
    print("styles: day + night")
    print()
    print("max_zoom  tiles/style     planned_disk(two styles)")
    for maximum in args.max_zooms:
        count = regional_tile_count(args.min_zoom, maximum)
        print(f"{maximum:>8}  {count:>12,}  {format_gib(planned_bytes(count))}")
    print()
    print(
        "Planning disk includes 25% headroom over the corridor-calibrated "
        f"{CALIBRATED_BYTES_PER_RASTER_TILE:,} bytes/tile baseline."
    )
    return 0


def command_extract(args: argparse.Namespace) -> int:
    region = REGION_BY_CODE[args.region]
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and not args.force:
        print(f"ERROR: output already exists: {output}", file=sys.stderr)
        return 2
    bbox = ",".join(str(value) for value in region.bounds)
    command = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{output.parent}:/output",
        PMTILES_IMAGE,
        "extract",
        args.source_url,
        f"/output/{output.name}",
        "--bbox",
        bbox,
        "--maxzoom",
        str(args.source_max_zoom),
    ]
    print("Extracting one regional Protomaps PMTiles source:")
    print(" ".join(command))
    completed = subprocess.run(command, check=False)
    if completed.returncode:
        return completed.returncode
    verify = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{output.parent}:/output",
            PMTILES_IMAGE,
            "verify",
            f"/output/{output.name}",
        ],
        check=False,
    )
    return verify.returncode


def command_render(args: argparse.Namespace) -> int:
    region = REGION_BY_CODE[args.region]
    style = args.style
    _validate_renderer_template(args.renderer_url_template)
    output = args.output.resolve()
    partial = output.with_suffix(output.suffix + ".partial")
    partial.parent.mkdir(parents=True, exist_ok=True)
    expected = tile_count(region, args.min_zoom, args.max_zoom)
    estimated = math.ceil(
        expected * CALIBRATED_BYTES_PER_RASTER_TILE * PLANNING_HEADROOM
    )
    free = shutil.disk_usage(partial.parent).free
    if not partial.exists() and free < estimated:
        print(
            f"ERROR: estimated free-space need is {format_gib(estimated)}, "
            f"but only {format_gib(free)} is available.",
            file=sys.stderr,
        )
        return 2

    connection = sqlite3.connect(partial)
    try:
        _initialize_mbtiles(connection, region, style, args.min_zoom, args.max_zoom)
        existing = int(connection.execute("SELECT COUNT(*) FROM tiles").fetchone()[0])
        print(
            f"Building {region.name} {style}: expected={expected:,} "
            f"already_present={existing:,} output={partial}"
        )
        started = time.monotonic()
        completed = existing
        since_commit = 0
        for zoom in range(args.min_zoom, args.max_zoom + 1):
            x0, x1, y0, y1 = tile_rectangle(region, zoom)
            for x in range(x0, x1 + 1):
                for y in range(y0, y1 + 1):
                    tms_y = (1 << zoom) - 1 - y
                    if connection.execute(
                        "SELECT 1 FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
                        (zoom, x, tms_y),
                    ).fetchone() is not None:
                        continue
                    key = MapTileKey(zoom=zoom, x=x, y=y)
                    try:
                        png = _fetch_tile(
                            args.renderer_url_template,
                            style,
                            key,
                            timeout_s=args.timeout_s,
                        )
                    except (OSError, RuntimeError) as error:
                        connection.commit()
                        print(
                            f"ERROR: render failed at {zoom}/{x}/{y}: {error}; "
                            "partial output is safe to resume.",
                            file=sys.stderr,
                        )
                        return 3
                    connection.execute(
                        """
                        INSERT INTO tiles(zoom_level, tile_column, tile_row, tile_data)
                        VALUES (?, ?, ?, ?)
                        """,
                        (zoom, x, tms_y, png),
                    )
                    completed += 1
                    since_commit += 1
                    if since_commit >= args.commit_every:
                        connection.commit()
                        since_commit = 0
                    if completed % args.progress_every == 0 or completed == expected:
                        elapsed = max(0.001, time.monotonic() - started)
                        newly_completed = max(1, completed - existing)
                        rate = newly_completed / elapsed
                        remaining = max(0, expected - completed)
                        eta_hours = remaining / max(rate, 0.001) / 3600
                        print(
                            f"progress={completed:,}/{expected:,} "
                            f"rate={rate:,.1f} tiles/s eta={eta_hours:,.1f}h"
                        )
        connection.commit()
        actual = int(connection.execute("SELECT COUNT(*) FROM tiles").fetchone()[0])
        if actual != expected:
            print(
                f"ERROR: validation count mismatch: expected {expected:,}, got {actual:,}",
                file=sys.stderr,
            )
            return 4
        connection.execute(
            "INSERT OR REPLACE INTO metadata(name,value) VALUES (?,?)",
            ("rolling_thunder_refreshed_at", datetime.now(UTC).isoformat()),
        )
        connection.commit()
    finally:
        connection.close()

    if output.exists():
        print(f"ERROR: final output already exists: {output}", file=sys.stderr)
        return 5
    partial.replace(output)
    print(f"PASS: validated package complete: {output}")
    return 0


def _initialize_mbtiles(
    connection: sqlite3.Connection,
    region: Region,
    style: str,
    min_zoom: int,
    max_zoom: int,
) -> None:
    connection.executescript(
        """
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS metadata (
            name TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tiles (
            zoom_level INTEGER NOT NULL,
            tile_column INTEGER NOT NULL,
            tile_row INTEGER NOT NULL,
            tile_data BLOB NOT NULL,
            PRIMARY KEY (zoom_level, tile_column, tile_row)
        );
        """
    )
    bounds = ",".join(str(value) for value in region.bounds)
    metadata = {
        "name": f"Rolling Thunder {region.name} {style} offline map",
        "type": "baselayer",
        "version": datetime.now(UTC).strftime("%Y.%m.%d"),
        "format": "png",
        "scheme": "tms",
        "bounds": bounds,
        "minzoom": str(min_zoom),
        "maxzoom": str(max_zoom),
        "attribution": "© OpenStreetMap contributors · Protomaps",
        "rolling_thunder_id": f"{region.code}-{style}-z{min_zoom}-z{max_zoom}",
        "rolling_thunder_style": style,
        "rolling_thunder_priority": "100",
    }
    connection.executemany(
        "INSERT OR IGNORE INTO metadata(name,value) VALUES (?,?)",
        metadata.items(),
    )
    connection.commit()


def _fetch_tile(
    template: str,
    style: str,
    key: MapTileKey,
    *,
    timeout_s: float,
) -> bytes:
    url = template.format(style=style, z=key.zoom, x=key.x, y=key.y)
    request = Request(
        url,
        headers={"Accept": "image/png", "User-Agent": "RollingThunder-MapBuilder/4.1"},
    )
    try:
        with urlopen(request, timeout=timeout_s) as response:
            body = response.read(2_000_001)
    except (URLError, TimeoutError, OSError) as error:
        raise OSError(str(error)) from error
    return validate_map_tile_png(body)


def _validate_renderer_template(template: str) -> None:
    lowered = template.lower()
    for token in ("{style}", "{z}", "{x}", "{y}"):
        if token not in template:
            raise ValueError(f"Renderer URL template must contain {token}.")
    forbidden = ("tile.openstreetmap.org", "vector.openstreetmap.org")
    if any(host in lowered for host in forbidden):
        raise ValueError(
            "Public OpenStreetMap tile services must not be used for regional generation."
        )


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    subparsers = root.add_subparsers(dest="command", required=True)

    estimate = subparsers.add_parser("estimate")
    estimate.add_argument("--min-zoom", type=int, default=DEFAULT_MIN_ZOOM)
    estimate.add_argument(
        "--max-zooms",
        type=int,
        nargs="+",
        default=[15, 16, 17, 18],
    )
    estimate.set_defaults(func=command_estimate)

    extract = subparsers.add_parser("extract")
    extract.add_argument("region", choices=sorted(REGION_BY_CODE))
    extract.add_argument("--source-url", required=True)
    extract.add_argument("--source-max-zoom", type=int, default=15)
    extract.add_argument("--output", type=Path, required=True)
    extract.add_argument("--force", action="store_true")
    extract.set_defaults(func=command_extract)

    render = subparsers.add_parser("render")
    render.add_argument("region", choices=sorted(REGION_BY_CODE))
    render.add_argument("style", choices=("day", "night"))
    render.add_argument("--renderer-url-template", required=True)
    render.add_argument("--output", type=Path, required=True)
    render.add_argument("--min-zoom", type=int, default=DEFAULT_MIN_ZOOM)
    render.add_argument("--max-zoom", type=int, default=DEFAULT_MAX_ZOOM)
    render.add_argument("--timeout-s", type=float, default=15.0)
    render.add_argument("--commit-every", type=int, default=1_000)
    render.add_argument("--progress-every", type=int, default=10_000)
    render.set_defaults(func=command_render)
    return root


def main() -> int:
    args = parser().parse_args()
    if getattr(args, "min_zoom", DEFAULT_MIN_ZOOM) < 0:
        raise SystemExit("minimum zoom must be non-negative")
    if hasattr(args, "max_zoom") and args.max_zoom < args.min_zoom:
        raise SystemExit("maximum zoom must be at least minimum zoom")
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
