"""Pure, conservative MeshCore geographic relevance using published GPS samples.

No GPS receiver, map matcher, geocoder, network call, or RF path is owned here.
A caller may supply at most one timestamped GPS sample per second.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


_EARTH_RADIUS_M = 6_371_000.0
_MIN_DISPLACEMENT_M = 15.0
_MAX_REALISTIC_SPEED_MPS = 90.0


@dataclass(frozen=True, slots=True)
class GeoPoint:
    """Verified geographic position in decimal degrees."""

    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        if (
            not math.isfinite(self.latitude)
            or not math.isfinite(self.longitude)
            or not -90 <= self.latitude <= 90
            or not -180 <= self.longitude <= 180
        ):
            raise ValueError("Invalid coordinates")


@dataclass(frozen=True, slots=True)
class VehicleFix:
    """One observation from Rolling Thunder's existing published GPS state."""

    point: GeoPoint
    observed_at: datetime
    accuracy_m: float
    speed_mps: float | None = None
    course_deg: float | None = None

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("GPS timestamp must be timezone-aware")
        if not math.isfinite(self.accuracy_m) or not 0 <= self.accuracy_m <= 150:
            raise ValueError("Invalid GPS accuracy")
        if self.speed_mps is not None and (
            not math.isfinite(self.speed_mps)
            or self.speed_mps < 0
            or self.speed_mps > _MAX_REALISTIC_SPEED_MPS
        ):
            raise ValueError("Invalid GPS speed")
        if self.course_deg is not None and (
            not math.isfinite(self.course_deg)
            or not 0 <= self.course_deg < 360
        ):
            raise ValueError("Invalid GPS course")


class Relevance(StrEnum):
    """Geographic relevance, with route confirmation explicitly separate."""

    AHEAD_CONFIRMED = "ahead_confirmed_route"
    POSSIBLY_AHEAD = "possibly_ahead"
    NEARBY_ROUTE_UNKNOWN = "nearby_route_unknown"
    BEHIND = "behind"
    NOT_RELEVANT = "not_relevant"
    INSUFFICIENT = "insufficient_information"


@dataclass(frozen=True, slots=True)
class RelevanceResult:
    """Conservative incident relationship without implied route certainty."""

    relevance: Relevance
    distance_m: float | None
    bearing_deg: float | None
    heading_deg: float | None


def distance_bearing(origin: GeoPoint, destination: GeoPoint) -> tuple[float, float]:
    """Return haversine distance (metres) and initial great-circle bearing."""
    lat1, lat2 = math.radians(origin.latitude), math.radians(destination.latitude)
    delta_lat = lat2 - lat1
    delta_lon = math.radians(destination.longitude - origin.longitude)
    hav = math.sin(delta_lat / 2) ** 2 + (
        math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    distance = 2 * _EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(hav)))
    y = math.sin(delta_lon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - (
        math.sin(lat1) * math.cos(lat2) * math.cos(delta_lon)
    )
    bearing = (math.degrees(math.atan2(y, x)) + 360) % 360
    return distance, bearing


class PublishedGpsHeading:
    """Bounded 5-second history of existing GPS snapshots; no new polling."""

    def __init__(self) -> None:
        self._fixes: deque[VehicleFix] = deque(maxlen=6)

    def offer(self, fix: VehicleFix) -> bool:
        """Accept new samples no more frequently than 1 Hz, reject out-of-order."""
        timestamp = fix.observed_at.astimezone(UTC)
        if self._fixes:
            interval = (timestamp - self._fixes[-1].observed_at.astimezone(UTC))
            if interval.total_seconds() < 1:
                return False
        self._fixes.append(fix)
        while self._fixes and (
            timestamp - self._fixes[0].observed_at.astimezone(UTC)
        ).total_seconds() > 5:
            self._fixes.popleft()
        return True

    def latest(self, now: datetime, *, max_age_s: float = 10) -> VehicleFix | None:
        """Return fresh GPS only; the consumer owns its clock/source verification."""
        if now.tzinfo is None or now.utcoffset() is None or not self._fixes:
            return None
        age = (
            now.astimezone(UTC) - self._fixes[-1].observed_at.astimezone(UTC)
        ).total_seconds()
        if age < 0 or age > max_age_s:
            return None
        return self._fixes[-1]

    def heading(self, now: datetime) -> float | None:
        """Prefer valid moving course; otherwise derive from 2–5 s displacement."""
        latest = self.latest(now)
        if latest is None:
            return None
        if latest.speed_mps is not None:
            if latest.speed_mps < 1.5:
                return None
            if latest.course_deg is not None:
                return latest.course_deg
        if len(self._fixes) < 2:
            return None
        older = self._fixes[0]
        seconds = (
            latest.observed_at.astimezone(UTC) - older.observed_at.astimezone(UTC)
        ).total_seconds()
        if seconds < 2 or seconds > 5:
            return None
        distance, bearing = distance_bearing(older.point, latest.point)
        if distance < max(
            _MIN_DISPLACEMENT_M, older.accuracy_m + latest.accuracy_m
        ):
            return None
        if distance / seconds > _MAX_REALISTIC_SPEED_MPS:
            return None
        return bearing


def assess_relevance(
    history: PublishedGpsHeading,
    incident: GeoPoint | None,
    now: datetime,
    *,
    maximum_distance_m: float = 20_000,
    route_confirmed: bool = False,
    incident_location_trusted: bool = False,
) -> RelevanceResult:
    """Classify geographic proximity, never infer route from bearing alone.

    `route_confirmed` must be supplied only by independent map matching using
    an incident's verified road and travel direction. Bearing is not proof.
    """
    if not math.isfinite(maximum_distance_m) or maximum_distance_m <= 0:
        raise ValueError("Invalid distance threshold")
    fix = history.latest(now)
    if fix is None or incident is None or not incident_location_trusted:
        return RelevanceResult(Relevance.INSUFFICIENT, None, None, None)

    distance, bearing = distance_bearing(fix.point, incident)
    heading = history.heading(now)
    if distance > maximum_distance_m:
        return RelevanceResult(Relevance.NOT_RELEVANT, distance, bearing, heading)
    if distance <= max(50.0, fix.accuracy_m):
        return RelevanceResult(
            Relevance.NEARBY_ROUTE_UNKNOWN, distance, bearing, heading
        )
    if heading is None:
        return RelevanceResult(
            Relevance.NEARBY_ROUTE_UNKNOWN, distance, bearing, None
        )

    delta = abs((bearing - heading + 180) % 360 - 180)
    if delta >= 135:
        return RelevanceResult(Relevance.BEHIND, distance, bearing, heading)
    if delta <= 60:
        state = (
            Relevance.AHEAD_CONFIRMED if route_confirmed
            else Relevance.POSSIBLY_AHEAD
        )
        return RelevanceResult(state, distance, bearing, heading)
    return RelevanceResult(
        Relevance.NEARBY_ROUTE_UNKNOWN, distance, bearing, heading
    )
