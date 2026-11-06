"""Independent GDAL/OGR comparison; run with system Python, no Pi dependency."""

import json
import random
import sqlite3
import sys
import zlib
from pathlib import Path

from osgeo import ogr

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from rolling_thunder.offline_county import CountyPolygon, OfflineCountyResolver


def resolve(db, lat, lon):
    rows = db.execute(
        """SELECT c.state,c.county,c.geometry FROM counties c JOIN bounds b ON b.id=c.id
           WHERE b.min_lon <= ? AND b.max_lon >= ?
             AND b.min_lat <= ? AND b.max_lat >= ?""",
        (lon, lon, lat, lat),
    )
    polygons = []
    for state, county, blob in rows:
        geometry = json.loads(zlib.decompress(blob))
        parts = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else (
            geometry["coordinates"],)
        for part in parts:
            polygons.append(CountyPolygon(
                state, county, tuple(map(tuple, part[0])),
                tuple(tuple(map(tuple, ring)) for ring in part[1:]),
            ))
    return OfflineCountyResolver(polygons).resolve(lat, lon)


def main(shp, sqlite):
    ds = ogr.Open(str(shp))
    layer = ds.GetLayer()
    total, invalid, compared, mismatches = 0, 0, 0, []
    rng = random.Random(380)
    with sqlite3.connect(f"file:{sqlite}?mode=ro", uri=True) as db:
        for feature in layer:
            total += 1
            geom = feature.GetGeometryRef()
            if not geom.IsValid():
                invalid += 1
            # OGR PointOnSurface guarantees an interior point of the county.
            p = geom.PointOnSurface()
            if p is None:
                continue
            lon, lat = p.GetX(), p.GetY()
            expected = (feature.GetField("STUSPS"), feature.GetField("NAME").upper())
            actual = resolve(db, lat, lon)
            compared += 1
            if actual != expected:
                mismatches.append((feature.GetField("GEOID"), expected, actual))
            if total % 10 == 0:
                minx, maxx, miny, maxy = geom.GetEnvelope()
                for _ in range(2):
                    x, y = rng.uniform(minx, maxx), rng.uniform(miny, maxy)
                    if geom.Contains(ogr.CreateGeometryFromWkt(f"POINT ({x} {y})")):
                        compared += 1
                        actual = resolve(db, y, x)
                        if actual != expected:
                            mismatches.append((feature.GetField("GEOID"), expected, actual))
    print(f"ogr_features={total} invalid_geometry={invalid} interior_checks={compared} mismatches={len(mismatches)}")
    print("sample_mismatches", mismatches[:12])
    if total != 3235 or invalid or mismatches:
        raise SystemExit(1)


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
