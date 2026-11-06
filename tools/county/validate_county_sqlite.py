"""Read-only source-artifact checks and example locations, not a runtime adapter."""

import json
import sqlite3
import sys
import zlib
from pathlib import Path

from rolling_thunder.offline_county import CountyPolygon, OfflineCountyResolver


def resolve(db: sqlite3.Connection, lat: float, lon: float):
    rows = db.execute(
        """SELECT c.state,c.county,c.geometry FROM counties c JOIN bounds b ON b.id=c.id
           WHERE b.min_lon <= ? AND b.max_lon >= ?
             AND b.min_lat <= ? AND b.max_lat >= ?""",
        (lon, lon, lat, lat),
    )
    polygons = []
    for state, county, blob in rows:
        geometry = json.loads(zlib.decompress(blob))
        parts = (geometry["coordinates"] if geometry["type"] == "MultiPolygon"
                 else (geometry["coordinates"],))
        for part in parts:
            polygons.append(CountyPolygon(
                state, county,
                tuple(tuple(p) for p in part[0]),
                tuple(tuple(tuple(p) for p in ring) for ring in part[1:]),
            ))
    return OfflineCountyResolver(polygons).resolve(lat, lon)


def main(path: Path) -> None:
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
        print("integrity", db.execute("PRAGMA integrity_check").fetchone()[0])
        count = db.execute("SELECT COUNT(*) FROM counties").fetchone()[0]
        assert count == 3235, count
        print("count", count)
        states = db.execute("SELECT COUNT(DISTINCT state) FROM counties").fetchone()[0]
        assert states == 56, states
        print("states_and_territories", states)
        for name, lat, lon, expected in (
            ("Waynesville OH", 39.5298, -84.0866, ("OH", "WARREN")),
            ("Columbus OH", 39.9612, -82.9988, ("OH", "FRANKLIN")),
            ("Dayton OH", 39.7589, -84.1916, ("OH", "MONTGOMERY")),
            ("Cincinnati OH", 39.1031, -84.5120, ("OH", "HAMILTON")),
            ("Los Angeles CA", 34.0522, -118.2437, ("CA", "LOS ANGELES")),
            ("New York NY", 40.7128, -74.0060, ("NY", "NEW YORK")),
            ("Anchorage AK", 61.2181, -149.9003, ("AK", "ANCHORAGE")),
            ("San Juan PR", 18.4655, -66.1057, ("PR", "SAN JUAN")),
            ("London UK", 51.5072, -0.1276, None),
        ):
            actual = resolve(db, lat, lon)
            print(name, actual)
            assert actual == expected, (name, actual, expected)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
