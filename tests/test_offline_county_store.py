"""Indexed SQLite lookup using a tiny synthetic artifact."""

import json
import sqlite3
import zlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

from rolling_thunder.domain import GPSFixState, GPSPosition
from rolling_thunder.offline_county_store import IndexedCountyStore


def build(path: Path) -> None:
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE counties(id INTEGER PRIMARY KEY, state TEXT, county TEXT, geometry BLOB)")
        db.execute("CREATE VIRTUAL TABLE bounds USING rtree(id, min_lon, max_lon, min_lat, max_lat)")
        for index, (name, x) in enumerate((("WEST", -85.0), ("EAST", -84.0)), 1):
            ring = [[x, 39], [x + 1, 39], [x + 1, 40], [x, 40], [x, 39]]
            data = zlib.compress(json.dumps({"type": "Polygon", "coordinates": [ring]}).encode())
            db.execute("INSERT INTO counties VALUES (?, ?, ?, ?)", (index, "OH", name, data))
            db.execute("INSERT INTO bounds VALUES (?, ?, ?, ?, ?)", (index, x, x + 1, 39, 40))


def test_indexed_lookup_and_border(tmp_path: Path) -> None:
    path = tmp_path / "counties.sqlite"
    build(path)
    store = IndexedCountyStore(path)
    assert store.resolve(39.5, -84.5) == ("OH", "WEST")
    assert store.resolve(39.5, -83.5) == ("OH", "EAST")
    assert store.resolve(39.5, -84.0) is None
    assert store.resolve(39.5, -84.0001, uncertainty_m=100) is None
    assert store.resolve(41, -84.5) is None
    assert IndexedCountyStore(tmp_path / "missing.sqlite").resolve(39.5, -84.5) is None
    assert IndexedCountyStore(path, max_candidates=1).resolve(39.5, -84) is None


def test_frozen_gps_age_and_accuracy(tmp_path: Path) -> None:
    path = tmp_path / "counties.sqlite"
    build(path)
    store = IndexedCountyStore(path)
    now = datetime.now(UTC)
    fix = GPSPosition(fix_state=GPSFixState.TWO_DIMENSIONAL, latitude=39.5,
                      longitude=-84.5, accuracy_m=5, updated_at=now)
    assert store.resolve_gps(fix, at=now) == ("OH", "WEST")
    assert store.resolve_gps(fix, at=now + timedelta(seconds=11)) is None
    assert store.resolve_gps(fix, at=now - timedelta(seconds=1)) is None
    assert store.resolve_gps(fix.model_copy(update={"accuracy_m": None}), at=now) is None
