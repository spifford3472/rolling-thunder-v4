"""Offline deterministic local operating-jurisdiction resolution."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Iterable

Point = tuple[float, float]
Ring = tuple[Point, ...]
Polygon = tuple[Ring, ...]


@dataclass(frozen=True, slots=True)
class LocalJurisdiction:
    """Frozen jurisdiction derived from one accepted local coordinate pair."""

    state: str
    cq_zone: int
    itu_zone: int


@dataclass(frozen=True, slots=True)
class StateBoundary:
    """One state/equivalent boundary represented as one or more polygons."""

    state: str
    polygons: tuple[Polygon, ...]

    def __post_init__(self) -> None:
        normalized = self.state.strip().upper()
        if len(normalized) != 2 or not normalized.isalpha():
            raise ValueError("state boundary requires a two-character state code")
        if not self.polygons:
            raise ValueError("state boundary requires at least one polygon")
        for polygon in self.polygons:
            if not polygon or len(polygon[0]) < 3:
                raise ValueError("state polygon requires an exterior ring")
        object.__setattr__(self, "state", normalized)


class _PointRelation(StrEnum):
    OUTSIDE = "outside"
    INSIDE = "inside"
    BOUNDARY = "boundary"


_CQ_ZONE_BY_STATE: Final[dict[str, int]] = {
    **{state: 1 for state in ("AK",)},
    **{state: 3 for state in ("AZ", "CA", "ID", "NV", "OR", "UT", "WA")},
    **{
        state: 4
        for state in (
            "AL", "AR", "CO", "IA", "IL", "IN", "KS", "KY", "LA", "MI", "MN",
            "MO", "MS", "MT", "ND", "NE", "NM", "OH", "OK", "SD", "TN", "TX",
            "WI", "WY",
        )
    },
    **{
        state: 5
        for state in (
            "CT", "DC", "DE", "FL", "GA", "MA", "MD", "ME", "NC", "NH", "NJ",
            "NY", "PA", "RI", "SC", "VA", "VT", "WV",
        )
    },
    **{state: 31 for state in ("HI",)},
}

_ITU_ZONE_6_WHOLE: Final[frozenset[str]] = frozenset({"CA", "ID", "NV", "OR", "WA"})
_ITU_ZONE_7_WHOLE: Final[frozenset[str]] = frozenset(
    {"CO", "IA", "KS", "MN", "ND", "NE", "NM", "OK", "SD", "TX", "WY"}
)
_ITU_ZONE_8_WHOLE: Final[frozenset[str]] = frozenset(
    {
        "AL", "CT", "DC", "DE", "FL", "GA", "IN", "KY", "MA", "MD", "ME", "NC",
        "NH", "NJ", "NY", "OH", "PA", "RI", "SC", "VA", "VT", "WV",
    }
)
_ITU_110_SPLIT: Final[frozenset[str]] = frozenset({"AZ", "MT", "UT"})
_ITU_90_SPLIT: Final[frozenset[str]] = frozenset(
    {"AR", "IL", "LA", "MI", "MO", "MS", "TN", "WI"}
)


class LocalJurisdictionResolver:
    """Resolve state, CQ zone, and ITU zone without network I/O."""

    def __init__(self, boundaries: Iterable[StateBoundary]) -> None:
        materialized = tuple(boundaries)
        codes = [boundary.state for boundary in materialized]
        if len(set(codes)) != len(codes):
            raise ValueError("state boundaries must have unique state codes")
        self._boundaries = materialized

    def resolve(self, latitude: float, longitude: float) -> LocalJurisdiction | None:
        """Return one unambiguous supported U.S. jurisdiction or fail closed."""
        _validate_coordinate(latitude, longitude)
        states: list[str] = []
        for boundary in self._boundaries:
            relation = _boundary_relation(boundary, longitude, latitude)
            if relation is _PointRelation.BOUNDARY:
                return None
            if relation is _PointRelation.INSIDE:
                states.append(boundary.state)
        if len(states) != 1:
            return None

        state = states[0]
        cq_zone = _CQ_ZONE_BY_STATE.get(state)
        itu_zone = _itu_zone(state, longitude)
        if cq_zone is None or itu_zone is None:
            return None
        return LocalJurisdiction(state=state, cq_zone=cq_zone, itu_zone=itu_zone)


def _itu_zone(state: str, longitude: float) -> int | None:
    if state == "AK":
        if longitude == -141.0:
            return None
        return 1 if longitude < -141.0 else 2
    if state == "HI":
        return 61
    if state in _ITU_ZONE_6_WHOLE:
        return 6
    if state in _ITU_ZONE_7_WHOLE:
        return 7
    if state in _ITU_ZONE_8_WHOLE:
        return 8
    if state in _ITU_110_SPLIT:
        if longitude == -110.0:
            return None
        return 6 if longitude < -110.0 else 7
    if state in _ITU_90_SPLIT:
        if longitude == -90.0:
            return None
        return 7 if longitude < -90.0 else 8
    return None


def _validate_coordinate(latitude: float, longitude: float) -> None:
    for name, value, minimum, maximum in (
        ("latitude", latitude, -90.0, 90.0),
        ("longitude", longitude, -180.0, 180.0),
    ):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"{name} must be a real number")
        if not math.isfinite(value) or not minimum <= value <= maximum:
            raise ValueError(f"{name} is outside its valid range")


def _boundary_relation(
    boundary: StateBoundary,
    longitude: float,
    latitude: float,
) -> _PointRelation:
    found_inside = False
    for polygon in boundary.polygons:
        relation = _polygon_relation(polygon, longitude, latitude)
        if relation is _PointRelation.BOUNDARY:
            return relation
        if relation is _PointRelation.INSIDE:
            found_inside = True
    return _PointRelation.INSIDE if found_inside else _PointRelation.OUTSIDE


def _polygon_relation(
    polygon: Polygon,
    longitude: float,
    latitude: float,
) -> _PointRelation:
    exterior = _ring_relation(polygon[0], longitude, latitude)
    if exterior is not _PointRelation.INSIDE:
        return exterior
    for hole in polygon[1:]:
        relation = _ring_relation(hole, longitude, latitude)
        if relation is _PointRelation.BOUNDARY:
            return relation
        if relation is _PointRelation.INSIDE:
            return _PointRelation.OUTSIDE
    return _PointRelation.INSIDE


def _ring_relation(ring: Ring, longitude: float, latitude: float) -> _PointRelation:
    if len(ring) < 3:
        return _PointRelation.OUTSIDE
    inside = False
    previous = ring[-1]
    for current in ring:
        x1, y1 = previous
        x2, y2 = current
        if _point_on_segment(longitude, latitude, x1, y1, x2, y2):
            return _PointRelation.BOUNDARY
        if (y1 > latitude) != (y2 > latitude):
            x_intersection = (x2 - x1) * (latitude - y1) / (y2 - y1) + x1
            if longitude < x_intersection:
                inside = not inside
        previous = current
    return _PointRelation.INSIDE if inside else _PointRelation.OUTSIDE


def _point_on_segment(
    x: float,
    y: float,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
) -> bool:
    cross = (x - x1) * (y2 - y1) - (y - y1) * (x2 - x1)
    scale = max(1.0, abs(x1), abs(y1), abs(x2), abs(y2))
    if abs(cross) > 1e-12 * scale:
        return False
    return (
        min(x1, x2) <= x <= max(x1, x2)
        and min(y1, y2) <= y <= max(y1, y2)
    )
