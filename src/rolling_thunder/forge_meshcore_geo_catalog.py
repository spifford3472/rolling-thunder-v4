"""Forge-local, audited geographic site catalog; no online geocoding.

A record must originate from reviewed, site-specific map evidence. Import is
operator-run, never a runtime effect. Lookups are query-only, reject ambiguity,
and cannot attest to a radio message's truth or a vehicle's route.
"""

from __future__ import annotations

import os
import sqlite3
import stat
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from rolling_thunder.meshcore_geographic_relevance import GeoPoint
from rolling_thunder.meshcore_traffic_geocoding import (
    TrafficGeocodeRequest,
    TrafficGeocodeResult,
)

_SCHEMA = 1
_MAX_BATCH = 1000
_MAX_AGE = timedelta(days=7)


class GeoCatalogError(ValueError):
    """Rejected catalog integrity, provenance, or modification."""


@dataclass(frozen=True, slots=True)
class ReviewedRoadSite:
    """A source-specific waypoint; not an event location or incident proof."""

    road: str
    exit_or_mile: str
    region: str
    point: GeoPoint
    source: str
    source_record_id: str
    observed_at: datetime
    reviewed_at: datetime
    point_specific: bool
    # A landmark alone is never sufficient to verify the vehicle's route.
    route_alignment_verified: bool = False

    def __post_init__(self) -> None:
        if (
            not self.road
            or not self.exit_or_mile
            or not self.region
            or len(self.road) > 32
            or len(self.exit_or_mile) > 24
            or len(self.region) > 80
            or not self.source.strip()
            or len(self.source) > 96
            or not self.source_record_id.strip()
            or len(self.source_record_id) > 128
            or not self.point_specific
            or self.route_alignment_verified
        ):
            raise GeoCatalogError("Road site requires reviewed specific provenance")
        for timestamp in (self.observed_at, self.reviewed_at):
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise GeoCatalogError("Naive catalog timestamp")
        if self.reviewed_at < self.observed_at:
            raise GeoCatalogError("Review predates source observation")


def _private_database(path: Path) -> None:
    """Refuse symlinks, shared permissions or unexpected file owners."""

    if path.parent.is_symlink():
        raise GeoCatalogError("Unsafe catalog directory")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if stat.S_IMODE(path.parent.stat().st_mode) & 0o077:
        raise GeoCatalogError("Catalog parent must be owner-only")
    if path.is_symlink():
        raise GeoCatalogError("Catalog must not be a symlink")
    if path.exists() and (
        not path.is_file()
        or path.stat().st_uid != os.geteuid()
        or stat.S_IMODE(path.stat().st_mode) & 0o077
    ):
        raise GeoCatalogError("Unsafe existing catalog permissions")
    if not path.exists():
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        os.close(fd)


class ForgeRoadSiteCatalog:
    """Dedicated SQLite catalog with explicit one-time import and safe lookup."""

    def __init__(self, path: Path, *, initialize: bool = False) -> None:
        self._path = path
        if initialize:
            _private_database(path)
            with sqlite3.connect(path) as db:
                db.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS catalog_schema(
                        version INTEGER PRIMARY KEY CHECK(version=1)
                    );
                    INSERT OR IGNORE INTO catalog_schema VALUES (1);
                    CREATE TABLE IF NOT EXISTS road_sites(
                        source TEXT NOT NULL,
                        source_record_id TEXT NOT NULL,
                        road TEXT NOT NULL,
                        exit_or_mile TEXT NOT NULL,
                        region TEXT NOT NULL,
                        latitude REAL NOT NULL,
                        longitude REAL NOT NULL,
                        observed_at TEXT NOT NULL,
                        reviewed_at TEXT NOT NULL,
                        point_specific INTEGER NOT NULL CHECK(point_specific=1),
                        PRIMARY KEY(source, source_record_id)
                    );
                    CREATE INDEX IF NOT EXISTS road_sites_lookup
                        ON road_sites(region,road,exit_or_mile);
                    """
                )
        self._verify()

    def _connect(self) -> sqlite3.Connection:
        if not self._path.is_file() or self._path.is_symlink():
            raise GeoCatalogError("Catalog unavailable")
        if stat.S_IMODE(self._path.stat().st_mode) & 0o077:
            raise GeoCatalogError("Catalog permissions too broad")
        db = sqlite3.connect(
            f"file:{self._path.resolve().as_posix()}?mode=ro", uri=True, timeout=1.0
        )
        db.execute("PRAGMA query_only=ON")
        return db

    def _verify(self) -> None:
        with self._connect() as db:
            if db.execute("SELECT version FROM catalog_schema").fetchall() != [(1,)]:
                raise GeoCatalogError("Unexpected catalog schema")
            if db.execute("PRAGMA quick_check").fetchone() != ("ok",):
                raise GeoCatalogError("Corrupt geographic catalog")

    def import_reviewed(self, sites: tuple[ReviewedRoadSite, ...], *, now: datetime) -> int:
        """Explicit atomic import with immutable source identities; no network."""

        if not 1 <= len(sites) <= _MAX_BATCH:
            raise GeoCatalogError("Invalid import batch")
        if now.tzinfo is None or now.utcoffset() is None:
            raise GeoCatalogError("Import time must be timezone-aware")
        utc_now = now.astimezone(UTC)
        for site in sites:
            if (
                site.reviewed_at > utc_now
                or site.observed_at > utc_now
                or utc_now - site.reviewed_at > _MAX_AGE
            ):
                raise GeoCatalogError("Source review stale or future")
        self._verify()
        added = 0
        with sqlite3.connect(self._path, timeout=3.0) as db:
            db.execute("PRAGMA synchronous=FULL")
            for site in sites:
                fields = (
                    site.source,
                    site.source_record_id,
                    site.road,
                    site.exit_or_mile,
                    site.region,
                    site.point.latitude,
                    site.point.longitude,
                    site.observed_at.astimezone(UTC).isoformat(),
                    site.reviewed_at.astimezone(UTC).isoformat(),
                    1,
                )
                existing = db.execute(
                    "SELECT source,source_record_id,road,exit_or_mile,region,"
                    "latitude,longitude,observed_at,reviewed_at,point_specific "
                    "FROM road_sites WHERE source=? AND source_record_id=?",
                    fields[:2],
                ).fetchone()
                if existing is not None and existing != fields:
                    raise GeoCatalogError("Conflicting source identity; manual review")
                if existing is None:
                    db.execute("INSERT INTO road_sites VALUES (?,?,?,?,?,?,?,?,?,?)", fields)
                    added += 1
        return added

    def lookup(
        self, request: TrafficGeocodeRequest, *, now: datetime
    ) -> TrafficGeocodeResult | None:
        """Require precisely one fresh, exact source point; no route assertion."""

        if now.tzinfo is None or now.utcoffset() is None:
            raise GeoCatalogError("Lookup time must be timezone-aware")
        with self._connect() as db:
            rows = db.execute(
                "SELECT latitude,longitude,source,source_record_id,reviewed_at "
                "FROM road_sites WHERE road=? AND exit_or_mile=? AND region=? "
                "LIMIT 2",
                (request.road, request.exit_or_mile, request.region),
            ).fetchall()
        # Duplicates from multiple sources intentionally require reconciliation.
        if len(rows) != 1:
            return None
        latitude, longitude, source, source_id, review = rows[0]
        reviewed = datetime.fromisoformat(review)
        age = now.astimezone(UTC) - reviewed
        if age < timedelta(0) or age > _MAX_AGE:
            return None
        point = GeoPoint(float(latitude), float(longitude))
        return TrafficGeocodeResult(
            latitude=point.latitude,
            longitude=point.longitude,
            road=request.road,
            exit_or_mile=request.exit_or_mile,
            source=f"{source}:{source_id}"[:64],
            point_specific=True,
            route_alignment_verified=False,
        )

    def health(self) -> dict[str, int | str]:
        """Provide source-neutral schema status without revealing site details."""

        with self._connect() as db:
            count = db.execute("SELECT COUNT(*) FROM road_sites").fetchone()[0]
        return {"schema": "meshcore/road-sites/v1", "records": int(count), "ready": "catalog_valid"}
