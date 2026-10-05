#!/usr/bin/env python3
"""Generate the compact Rolling Thunder U.S. jurisdiction ZIP artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import shapefile

SOURCE_URL = "https://www2.census.gov/geo/tiger/TIGER2025/STATE/tl_2025_us_state.zip"
SUPPORTED_CODES = frozenset(
    {
        "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI",
        "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN",
        "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH",
        "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA",
        "WV", "WI", "WY",
    }
)
COORDINATE_DECIMALS = 6
FORMAT_VERSION = 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_zip", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument(
        "--generated-at",
        default=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        help="UTC provenance timestamp stored in the artifact",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source = args.source_zip
    if not source.is_file():
        raise SystemExit(f"source ZIP does not exist: {source}")

    source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="rolling-thunder-jurisdiction-") as temp_dir:
        temp = Path(temp_dir)
        with zipfile.ZipFile(source) as archive:
            archive.extractall(temp)
        shp_files = list(temp.glob("*.shp"))
        if len(shp_files) != 1:
            raise SystemExit(f"expected one shapefile, found {len(shp_files)}")
        states = _read_states(shp_files[0])

    codes = {entry["state"] for entry in states}
    if codes != SUPPORTED_CODES:
        missing = sorted(SUPPORTED_CODES - codes)
        extra = sorted(codes - SUPPORTED_CODES)
        raise SystemExit(f"unexpected state coverage: missing={missing} extra={extra}")

    args.destination.parent.mkdir(parents=True, exist_ok=True)
    index_states: list[dict[str, Any]] = []
    with zipfile.ZipFile(
        args.destination,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for state in states:
            code = state["state"]
            member = f"states/{code}.json"
            payload = {
                "state": code,
                "polygons": state["polygons"],
            }
            encoded = json.dumps(
                payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False
            ).encode("utf-8")
            archive.writestr(member, encoded)
            index_states.append(
                {
                    "state": code,
                    "bbox": state["bbox"],
                    "member": member,
                }
            )

        index = {
            "format_version": FORMAT_VERSION,
            "source": {
                "agency": "U.S. Census Bureau, Geography Division",
                "dataset": "2025 TIGER/Line State and Equivalent Entity National shapefile",
                "source_url": SOURCE_URL,
                "source_zip_sha256": source_sha256,
                "generated_at_utc": args.generated_at,
                "coordinate_decimals": COORDINATE_DECIMALS,
                "supported_scope": "50 states plus District of Columbia",
            },
            "states": index_states,
        }
        archive.writestr(
            "index.json",
            json.dumps(
                index, separators=(",", ":"), sort_keys=True, ensure_ascii=False
            ).encode("utf-8"),
        )

    artifact_bytes = args.destination.read_bytes()
    print(f"source_sha256={source_sha256}")
    print(f"artifact_sha256={hashlib.sha256(artifact_bytes).hexdigest()}")
    print(f"artifact_bytes={len(artifact_bytes)}")
    print(f"states={len(states)}")


def _read_states(shapefile_path: Path) -> list[dict[str, Any]]:
    reader = shapefile.Reader(str(shapefile_path))
    field_names = [field[0] for field in reader.fields[1:]]
    try:
        state_index = field_names.index("STUSPS")
    except ValueError as error:
        raise SystemExit("Census shapefile does not contain STUSPS") from error

    output: list[dict[str, Any]] = []
    for shape_record in reader.iterShapeRecords():
        state = str(shape_record.record[state_index]).strip().upper()
        if state not in SUPPORTED_CODES:
            continue
        geometry = shape_record.shape.__geo_interface__
        polygons = _geometry_polygons(geometry)
        if not polygons:
            raise SystemExit(f"state {state} has no polygon geometry")
        output.append(
            {
                "state": state,
                "bbox": _polygons_bbox(polygons),
                "polygons": polygons,
            }
        )
    output.sort(key=lambda entry: entry["state"])
    return output


def _geometry_polygons(geometry: dict[str, Any]) -> list[list[list[list[float]]]]:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if geometry_type == "Polygon":
        raw_polygons = [coordinates]
    elif geometry_type == "MultiPolygon":
        raw_polygons = coordinates
    else:
        raise SystemExit(f"unsupported Census geometry type: {geometry_type!r}")
    if not isinstance(raw_polygons, (list, tuple)):
        raise SystemExit("Census geometry coordinates are malformed")

    polygons: list[list[list[list[float]]]] = []
    for raw_polygon in raw_polygons:
        if not isinstance(raw_polygon, (list, tuple)):
            raise SystemExit("Census polygon is malformed")
        rings: list[list[list[float]]] = []
        for raw_ring in raw_polygon:
            if not isinstance(raw_ring, (list, tuple)):
                raise SystemExit("Census ring is malformed")
            points: list[list[float]] = []
            for raw_point in raw_ring:
                if not isinstance(raw_point, (list, tuple)) or len(raw_point) < 2:
                    raise SystemExit("Census point is malformed")
                longitude = round(float(raw_point[0]), COORDINATE_DECIMALS)
                latitude = round(float(raw_point[1]), COORDINATE_DECIMALS)
                point = [longitude, latitude]
                if not points or points[-1] != point:
                    points.append(point)
            if len(points) >= 4:
                if points[0] != points[-1]:
                    points.append(points[0])
                rings.append(points)
        if rings:
            polygons.append(rings)
    return polygons


def _polygons_bbox(polygons: list[list[list[list[float]]]]) -> list[float]:
    longitudes: list[float] = []
    latitudes: list[float] = []
    for polygon in polygons:
        exterior = polygon[0]
        longitudes.extend(point[0] for point in exterior)
        latitudes.extend(point[1] for point in exterior)
    return [
        min(longitudes),
        min(latitudes),
        max(longitudes),
        max(latitudes),
    ]


if __name__ == "__main__":
    main()
