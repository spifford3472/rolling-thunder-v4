"""Conservative, dependency-free offline county lookup for frozen GPS coordinates.

Only prevalidated polygon records are accepted. This module performs no I/O,
network requests, or GPS acquisition; callers own data loading and fix freshness.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from itertools import pairwise
from math import isfinite

Point = tuple[float, float]  # longitude, latitude
Ring = tuple[Point, ...]


@dataclass(frozen=True)
class CountyPolygon:
    """One polygon component of a named county, with optional interior holes."""

    state: str
    county: str
    exterior: Ring
    holes: tuple[Ring, ...] = ()

    def __post_init__(self) -> None:
        if not self.state or not self.county:
            raise ValueError("County identity is required")
        for ring in (self.exterior, *self.holes):
            if len(ring) < 4 or ring[0] != ring[-1]:
                raise ValueError("Polygon rings must be closed and have four or more points")
            if any(
                not isfinite(lon) or not isfinite(lat)
                or not -180 <= lon <= 180 or not -90 <= lat <= 90
                for lon, lat in ring
            ):
                raise ValueError("Polygon coordinates must be finite WGS84 degrees")


def _ring_contains(point: Point, ring: Ring, *, epsilon: float) -> bool | None:
    """True inside, False outside, None on/near a boundary."""
    x, y = point
    inside = False
    for (ax, ay), (bx, by) in pairwise(ring):
        dx, dy = bx - ax, by - ay
        squared = dx * dx + dy * dy
        if squared:
            fraction = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / squared))
            if (x - ax - fraction * dx) ** 2 + (y - ay - fraction * dy) ** 2 <= epsilon**2:
                return None
        if (ay > y) != (by > y):
            crossing = ax + (y - ay) * dx / dy
            if crossing > x:
                inside = not inside
    return inside


class OfflineCountyResolver:
    """Resolve unique interior county membership; unknown/ambiguous returns None."""

    def __init__(self, polygons: Iterable[CountyPolygon], *, boundary_degrees: float = 0.0001):
        if not isfinite(boundary_degrees) or boundary_degrees <= 0:
            raise ValueError("A positive finite boundary buffer is required")
        self._polygons = tuple(polygons)
        self._boundary_degrees = boundary_degrees

    def resolve(self, latitude: float | None, longitude: float | None) -> tuple[str, str] | None:
        """Return (state, county) only for an unambiguous point inside a polygon."""
        if (
            latitude is None or longitude is None
            or not isfinite(latitude) or not isfinite(longitude)
            or not -90 <= latitude <= 90 or not -180 <= longitude <= 180
        ):
            return None
        point = (longitude, latitude)
        matches: set[tuple[str, str]] = set()
        for polygon in self._polygons:
            exterior = _ring_contains(point, polygon.exterior, epsilon=self._boundary_degrees)
            if exterior is None:
                return None
            if not exterior:
                continue
            holes = tuple(
                _ring_contains(point, ring, epsilon=self._boundary_degrees)
                for ring in polygon.holes
            )
            if None in holes:
                return None
            if True not in holes:
                matches.add((polygon.state, polygon.county))
                if len(matches) > 1:
                    return None
        return next(iter(matches)) if len(matches) == 1 else None
