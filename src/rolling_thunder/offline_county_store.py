"""Bounded read-only R-tree county lookup for a validated local SQLite artifact."""

from __future__ import annotations

import json
import sqlite3
import zlib
from datetime import UTC, datetime
from math import cos, isfinite, radians
from pathlib import Path
from typing import TYPE_CHECKING

from rolling_thunder.offline_county import CountyPolygon, OfflineCountyResolver

if TYPE_CHECKING:
    from rolling_thunder.domain import GPSPosition


class IndexedCountyStore:
    """Offline county lookup; no network, writes, or mutable GPS dependencies."""

    def __init__(self, path: Path, *, max_candidates: int = 16) -> None:
        if max_candidates < 1:
            raise ValueError("max_candidates must be positive")
        self._path = path
        self._max_candidates = max_candidates

    def resolve(
        self, latitude: float | None, longitude: float | None, *,
        uncertainty_m: float = 30.0,
    ) -> tuple[str, str] | None:
        """Return unknown if geometry, file, candidate count or accuracy is uncertain.

        A conservative degree buffer includes the uncertainty radius and a
        fixed 20-m allowance for boundary/source datum discrepancies. This
        cannot make generalized Census cartographic boundaries survey-grade.
        """
        if (
            latitude is None or longitude is None
            or not isfinite(latitude) or not isfinite(longitude)
            or not -90 <= latitude <= 90 or not -180 <= longitude <= 180
            or not isfinite(uncertainty_m) or uncertainty_m < 0
        ):
            return None
        buffer_m = max(uncertainty_m, 10.0) + 20.0
        latitude_degrees = buffer_m / 110_000.0
        longitude_scale = cos(radians(latitude))
        if longitude_scale < 0.01:
            return None
        longitude_degrees = buffer_m / (110_000.0 * longitude_scale)
        # The underlying planar polygon test uses one conservative angular
        # radius, so choose the larger of latitude/longitude degree buffers.
        epsilon = max(latitude_degrees, longitude_degrees)
        if epsilon > 0.25:
            return None
        try:
            with sqlite3.connect(
                f"{self._path.resolve().as_uri()}?mode=ro&immutable=1", uri=True,
                timeout=0.1,
            ) as connection:
                rows = connection.execute(
                    """SELECT c.state, c.county, c.geometry FROM counties c
                       JOIN bounds b ON b.id=c.id
                       WHERE b.min_lon <= ? AND b.max_lon >= ?
                         AND b.min_lat <= ? AND b.max_lat >= ?
                       LIMIT ?""",
                    (
                        longitude + epsilon, longitude - epsilon,
                        latitude + epsilon, latitude - epsilon,
                        self._max_candidates + 1,
                    ),
                ).fetchall()
            if len(rows) > self._max_candidates:
                return None
            polygons: list[CountyPolygon] = []
            for state, county, blob in rows:
                geometry = json.loads(zlib.decompress(blob))
                parts = (
                    geometry["coordinates"]
                    if geometry["type"] == "MultiPolygon"
                    else (geometry["coordinates"],)
                )
                for part in parts:
                    polygons.append(CountyPolygon(
                        state, county, tuple(map(tuple, part[0])),
                        tuple(tuple(map(tuple, ring)) for ring in part[1:]),
                    ))
            return OfflineCountyResolver(polygons, boundary_degrees=epsilon).resolve(
                latitude, longitude
            )
        except (OSError, sqlite3.Error, ValueError, TypeError, KeyError, IndexError, zlib.error):
            return None

    def resolve_gps(
        self, position: GPSPosition | None, *, at: datetime,
        max_age_s: float = 10.0,
    ) -> tuple[str, str] | None:
        """Resolve only a valid, fresh frozen fix with reported uncertainty.

        Callers must freeze the GPSPosition at the intended QSO lifecycle point;
        this method never acquires a new position.
        """
        from rolling_thunder.domain import GPSFixState

        if position is None or position.fix_state is GPSFixState.NO_FIX:
            return None
        if at.tzinfo is None or not isfinite(max_age_s) or max_age_s < 0:
            return None
        age = (at.astimezone(UTC) - position.updated_at).total_seconds()
        if age < 0 or age > max_age_s or position.accuracy_m is None:
            return None
        return self.resolve(
            position.latitude, position.longitude, uncertainty_m=position.accuracy_m
        )
