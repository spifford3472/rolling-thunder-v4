"""Offline deterministic local operating-jurisdiction resolution."""

from __future__ import annotations

import json
import math
import zipfile
from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

JURISDICTION_ARTIFACT_FORMAT_VERSION: Final = 2
_ARTIFACT_CACHE_SIZE: Final = 3

Point = tuple[float, float]
Ring = tuple[Point, ...]
Polygon = tuple[Ring, ...]
BoundingBox = tuple[float, float, float, float]


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


@dataclass(frozen=True, slots=True)
class _ArtifactState:
    state: str
    bbox: BoundingBox
    member: str


class _PointRelation(StrEnum):
    OUTSIDE = "outside"
    INSIDE = "inside"
    BOUNDARY = "boundary"


_CQ_ZONE_BY_STATE: Final[dict[str, int]] = {
    "AK": 1,
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
    "HI": 31,
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
        self._boundaries: tuple[StateBoundary, ...] | None = materialized
        self._artifact_path: Path | None = None
        self._artifact_states: tuple[_ArtifactState, ...] = ()
        self._state_cache: OrderedDict[str, StateBoundary] = OrderedDict()

    @classmethod
    def from_artifact(cls, path: Path) -> LocalJurisdictionResolver:
        """Load only the compact index from a generated jurisdiction archive."""
        artifact_states = load_artifact_index(path)
        resolver = cls(())
        resolver._boundaries = None
        resolver._artifact_path = path
        resolver._artifact_states = artifact_states
        return resolver

    def resolve(self, latitude: float, longitude: float) -> LocalJurisdiction | None:
        """Return one unambiguous supported U.S. jurisdiction or fail closed."""
        _validate_coordinate(latitude, longitude)
        states: list[str] = []

        if self._boundaries is not None:
            candidates = self._boundaries
        else:
            candidates = tuple(
                self._load_artifact_state(entry)
                for entry in self._artifact_states
                if _bbox_contains(entry.bbox, longitude, latitude)
            )

        for boundary in candidates:
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

    def _load_artifact_state(self, entry: _ArtifactState) -> StateBoundary:
        cached = self._state_cache.get(entry.state)
        if cached is not None:
            self._state_cache.move_to_end(entry.state)
            return cached

        artifact_path = self._artifact_path
        if artifact_path is None:
            raise ValueError("jurisdiction resolver has no artifact path")

        try:
            with zipfile.ZipFile(artifact_path) as archive:
                raw = archive.read(entry.member)
        except (OSError, KeyError, zipfile.BadZipFile) as error:
            raise ValueError(
                f"jurisdiction artifact state could not be read: {entry.state}"
            ) from error

        boundary = _parse_state_boundary_json(raw, expected_state=entry.state)
        self._state_cache[entry.state] = boundary
        self._state_cache.move_to_end(entry.state)
        while len(self._state_cache) > _ARTIFACT_CACHE_SIZE:
            self._state_cache.popitem(last=False)
        return boundary


def load_artifact_index(path: Path) -> tuple[_ArtifactState, ...]:
    """Load and validate only the small index from a generated ZIP artifact."""
    try:
        with zipfile.ZipFile(path) as archive:
            raw = archive.read("index.json")
    except (OSError, KeyError, zipfile.BadZipFile) as error:
        raise ValueError(f"jurisdiction artifact could not be read: {path}") from error

    try:
        document = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError("jurisdiction artifact index is not valid JSON") from error

    if not isinstance(document, dict):
        raise TypeError("jurisdiction artifact index must be a JSON object")
    if document.get("format_version") != JURISDICTION_ARTIFACT_FORMAT_VERSION:
        raise ValueError("unsupported jurisdiction artifact format")

    raw_states = document.get("states")
    if not isinstance(raw_states, list) or not raw_states:
        raise ValueError("jurisdiction artifact requires indexed states")

    entries: list[_ArtifactState] = []
    seen: set[str] = set()
    for raw_state in raw_states:
        if not isinstance(raw_state, dict):
            raise TypeError("jurisdiction artifact state index is malformed")
        state = raw_state.get("state")
        member = raw_state.get("member")
        bbox = _parse_bbox(raw_state.get("bbox"))
        if not isinstance(state, str) or not isinstance(member, str):
            raise TypeError("jurisdiction artifact state index is malformed")
        normalized = state.strip().upper()
        if len(normalized) != 2 or not normalized.isalpha():
            raise ValueError("jurisdiction artifact state code is invalid")
        if normalized in seen:
            raise ValueError("jurisdiction artifact state codes must be unique")
        seen.add(normalized)
        entries.append(_ArtifactState(normalized, bbox, member))
    return tuple(entries)


def _parse_state_boundary_json(raw: bytes, *, expected_state: str) -> StateBoundary:
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(f"jurisdiction state {expected_state} is not valid JSON") from error
    if not isinstance(document, dict):
        raise TypeError(f"jurisdiction state {expected_state} must be an object")
    state = document.get("state")
    raw_polygons = document.get("polygons")
    if state != expected_state or not isinstance(raw_polygons, list):
        raise ValueError(f"jurisdiction state {expected_state} is malformed")

    polygons: list[Polygon] = []
    for raw_polygon in raw_polygons:
        if not isinstance(raw_polygon, list):
            raise TypeError(f"jurisdiction state {expected_state} polygon is malformed")
        rings: list[Ring] = []
        for raw_ring in raw_polygon:
            if not isinstance(raw_ring, list):
                raise TypeError(f"jurisdiction state {expected_state} ring is malformed")
            points: list[Point] = []
            for raw_point in raw_ring:
                if not isinstance(raw_point, list):
                    raise TypeError(
                        f"jurisdiction state {expected_state} point is malformed"
                    )
                if len(raw_point) != 2:
                    raise ValueError(
                        f"jurisdiction state {expected_state} point is malformed"
                    )
                if (
                    isinstance(raw_point[0], bool)
                    or isinstance(raw_point[1], bool)
                    or not isinstance(raw_point[0], (int, float))
                    or not isinstance(raw_point[1], (int, float))
                ):
                    raise TypeError(
                        f"jurisdiction state {expected_state} point is malformed"
                    )
                longitude = float(raw_point[0])
                latitude = float(raw_point[1])
                _validate_coordinate(latitude, longitude)
                points.append((longitude, latitude))
            rings.append(tuple(points))
        polygons.append(tuple(rings))
    return StateBoundary(state=expected_state, polygons=tuple(polygons))


def _parse_bbox(raw_bbox: object) -> BoundingBox:
    if not isinstance(raw_bbox, list) or len(raw_bbox) != 4:
        raise TypeError("jurisdiction artifact bbox is malformed")
    values: list[float] = []
    for value in raw_bbox:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("jurisdiction artifact bbox is malformed")
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("jurisdiction artifact bbox is malformed")
        values.append(number)
    west, south, east, north = values
    if west > east or south > north:
        raise ValueError("jurisdiction artifact bbox is malformed")
    _validate_coordinate(south, west)
    _validate_coordinate(north, east)
    return west, south, east, north


def _bbox_contains(
    bbox: BoundingBox,
    longitude: float,
    latitude: float,
) -> bool:
    west, south, east, north = bbox
    return west <= longitude <= east and south <= latitude <= north


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
        if not _bbox_contains(_polygon_bbox(polygon), longitude, latitude):
            continue
        relation = _polygon_relation(polygon, longitude, latitude)
        if relation is _PointRelation.BOUNDARY:
            return relation
        if relation is _PointRelation.INSIDE:
            found_inside = True
    return _PointRelation.INSIDE if found_inside else _PointRelation.OUTSIDE


def _polygon_bbox(polygon: Polygon) -> BoundingBox:
    exterior = polygon[0]
    longitudes = [point[0] for point in exterior]
    latitudes = [point[1] for point in exterior]
    return min(longitudes), min(latitudes), max(longitudes), max(latitudes)


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
