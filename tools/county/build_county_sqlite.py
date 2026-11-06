"""Build an indexed offline county artifact from the pinned Census SHP archive.

Development-only tool: requires pyshp; never executes on anvilmobile.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import zipfile
import zlib
from pathlib import Path

import shapefile


def build(source: Path, destination: Path) -> None:
    with zipfile.ZipFile(source) as archive:
        prefix = "cb_2025_us_county_500k"
        with shapefile.Reader(
            shp=archive.open(prefix + ".shp"),
            shx=archive.open(prefix + ".shx"),
            dbf=archive.open(prefix + ".dbf"),
            encoding="utf-8",
        ) as reader:
            if len(reader) != 3235:
                raise ValueError(f"Unexpected county count: {len(reader)}")
            if destination.exists():
                raise FileExistsError(destination)
            with sqlite3.connect(destination) as db:
                db.executescript("""
                    CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE counties (
                        id INTEGER PRIMARY KEY, geoid TEXT NOT NULL UNIQUE,
                        state TEXT NOT NULL, county TEXT NOT NULL,
                        geometry BLOB NOT NULL
                    );
                    CREATE VIRTUAL TABLE bounds USING rtree(
                        id, min_lon, max_lon, min_lat, max_lat
                    );
                """)
                db.executemany("INSERT INTO metadata VALUES (?, ?)", (
                    ("source", "US Census 2025 county 1:500000"),
                    ("source_sha256", hashlib.sha256(source.read_bytes()).hexdigest()),
                    ("coordinate_system", "NAD83 EPSG:4269; treated as WGS84 approximation"),
                    ("format", "zlib-compressed GeoJSON Polygon/MultiPolygon coordinates"),
                ))
                count = 0
                for record in reader.iterShapeRecords():
                    attrs = record.record.as_dict()
                    geom = record.shape.__geo_interface__
                    if geom["type"] not in {"Polygon", "MultiPolygon"}:
                        raise ValueError(f"Unsupported geometry {geom['type']}")
                    if not attrs["STUSPS"] or not attrs["NAME"]:
                        raise ValueError("Missing county identity")
                    count += 1
                    db.execute(
                        "INSERT INTO counties VALUES (?, ?, ?, ?, ?)",
                        (count, attrs["GEOID"], attrs["STUSPS"], attrs["NAME"].upper(),
                         zlib.compress(json.dumps(geom, separators=(",", ":")).encode(), 9)),
                    )
                    min_lon, min_lat, max_lon, max_lat = record.shape.bbox
                    db.execute("INSERT INTO bounds VALUES (?, ?, ?, ?, ?)",
                               (count, min_lon, max_lon, min_lat, max_lat))
                if count != 3235:
                    raise ValueError("Missing county records")
                if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("SQLite integrity check failed")
    print(f"counties={count} bytes={destination.stat().st_size}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    build(args.source, args.destination)
