"""Analysis-only traffic relevance from existing GPS and externally verified evidence.

All inputs are injected. No broker cursor, geocoder, map, serial, UI, or radio
side effects. Reported road references are never considered verified places.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from rolling_thunder.meshcore_geographic_relevance import (
    GeoPoint,
    PublishedGpsHeading,
    Relevance,
    RelevanceResult,
    VehicleFix,
    assess_relevance,
)
from rolling_thunder.meshcore_incident_classification import (
    ClassifiedIncident,
    IncidentCategory,
)
from rolling_thunder.meshcore_traffic_georeferences import (
    ReferenceQuality,
    TrafficGeoreference,
    extract_traffic_georeference,
)

_MAX_AGE = timedelta(minutes=10)
_GEO_MAX_AGE = timedelta(days=7)
_MAX_GPS_ACCURACY_M = 30.0


class AssessmentConfidence(StrEnum):
    """Bounded certainty in the geographic relationship, not incident truth."""

    UNKNOWN = "unknown"
    LOW = "low"
    MODERATE = "moderate"


@dataclass(frozen=True, slots=True)
class GeographicEvidence:
    """Geocode/map evidence, supplied by an independent reviewed provider.

    An ordinary street/road center is never a trusted incident point. A source
    must explicitly attest a specific intersection/exit or mile-marker site.
    """

    point: GeoPoint
    road: str
    exit_or_mile: str
    verified_at: datetime
    source: str
    point_specific: bool
    route_alignment_verified: bool = False
    direction_verified: str | None = None

    def __post_init__(self) -> None:
        if (
            self.verified_at.tzinfo is None
            or self.verified_at.utcoffset() is None
            or not self.road.strip()
            or not self.exit_or_mile.strip()
            or len(self.road) > 32
            or len(self.exit_or_mile) > 24
            or not self.source.strip()
            or len(self.source) > 64
        ):
            raise ValueError("Invalid geographic evidence")
        if self.direction_verified not in (None, "N", "S", "E", "W"):
            raise ValueError("Invalid verified traffic direction")


@dataclass(frozen=True, slots=True)
class TrafficRelevanceDecision:
    """Auditable, non-notifying assessment of an unverified traffic report."""

    relevance: Relevance
    confidence: AssessmentConfidence
    reason: str
    received_at: datetime
    road_references: TrafficGeoreference
    distance_m: float | None = None
    heading_deg: float | None = None
    bearing_deg: float | None = None
    verified_geocode_source: str | None = None
    is_verified_incident: bool = False

    @property
    def driver_alert_permitted(self) -> bool:
        """Explicit deny-all until a separately authorized notification policy."""

        return False


def assess_traffic_candidate(
    incident: ClassifiedIncident,
    history: PublishedGpsHeading,
    now: datetime,
    *,
    evidence: GeographicEvidence | None = None,
) -> TrafficRelevanceDecision:
    """Evaluate a bounded, fresh candidate without acquiring any new GPS.

    An exact, independently verified specific location is needed before even
    relative bearing may be assessed. A route assertion additionally requires
    matching route, direction and independent route-alignment evidence.
    """

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Evaluation time must be timezone aware")
    now_utc = now.astimezone(UTC)
    refs = extract_traffic_georeference(incident)

    def insufficient(reason: str) -> TrafficRelevanceDecision:
        return TrafficRelevanceDecision(
            Relevance.INSUFFICIENT,
            AssessmentConfidence.UNKNOWN,
            reason,
            incident.received_at,
            refs,
        )

    age = now_utc - incident.received_at.astimezone(UTC)
    if age < timedelta(0) or age > _MAX_AGE:
        return insufficient("report_outside_analysis_freshness_window")
    if incident.category == IncidentCategory.UNKNOWN or incident.channel_kind != "traffic":
        return insufficient("no_classified_public_traffic_incident")
    if refs.quality != ReferenceQuality.SPECIFIC_UNVERIFIED:
        return insufficient("insufficient_or_ambiguous_report_location")
    if evidence is None:
        return insufficient("no_independently_verified_geographic_evidence")

    evidence_age = now_utc - evidence.verified_at.astimezone(UTC)
    if evidence_age < timedelta(0) or evidence_age > _GEO_MAX_AGE:
        return insufficient("geographic_evidence_stale_or_future")
    if not evidence.point_specific:
        return insufficient("geocode_is_generic_road_not_incident_site")
    if evidence.road not in refs.roads:
        return insufficient("geocode_road_mismatch")
    if evidence.exit_or_mile not in refs.exits + refs.mile_markers:
        return insufficient("geocode_exit_or_mile_mismatch")

    latest = history.latest(now_utc)
    if latest is None:
        return insufficient("no_fresh_existing_gps")
    if latest.accuracy_m > _MAX_GPS_ACCURACY_M:
        return insufficient("gps_accuracy_insufficient")
    # Even when the receiver provides course over ground, require a second
    # existing sample 2–5 seconds apart before claiming movement relevance.
    if not history.has_recent_span(now_utc, min_seconds=2):
        return insufficient("insufficient_gps_sample_history")

    heading = history.heading(now_utc)
    if heading is None:
        # Proximity with stationary vehicle may still be informative, but
        # route relevance cannot be claimed.
        result = assess_relevance(
            history,
            evidence.point,
            now_utc,
            incident_location_trusted=True,
        )
    else:
        direction = refs.directions[0] if len(refs.directions) == 1 else None
        route_confirmed = bool(
            evidence.route_alignment_verified
            and direction is not None
            and evidence.direction_verified == direction
        )
        result = assess_relevance(
            history,
            evidence.point,
            now_utc,
            incident_location_trusted=True,
            route_confirmed=route_confirmed,
        )
    return _decision_from_result(incident, refs, evidence, result)


def _decision_from_result(
    incident: ClassifiedIncident,
    refs: TrafficGeoreference,
    evidence: GeographicEvidence,
    result: RelevanceResult,
) -> TrafficRelevanceDecision:
    """Describe evidence without claiming that the reported event is real."""

    reason = {
        Relevance.AHEAD_CONFIRMED: "independent_route_alignment_and_site_evidence",
        Relevance.POSSIBLY_AHEAD: "geometric_heading_only_route_not_confirmed",
        Relevance.BEHIND: "reported_site_behind_vehicle_heading",
        Relevance.NEARBY_ROUTE_UNKNOWN: "nearby_but_route_or_motion_unknown",
        Relevance.NOT_RELEVANT: "outside_local_relevance_radius",
        Relevance.INSUFFICIENT: "insufficient_geographic_or_gps_evidence",
    }[result.relevance]
    confidence = (
        AssessmentConfidence.MODERATE
        if result.relevance == Relevance.AHEAD_CONFIRMED
        else AssessmentConfidence.LOW
        if result.relevance != Relevance.INSUFFICIENT
        else AssessmentConfidence.UNKNOWN
    )
    return TrafficRelevanceDecision(
        relevance=result.relevance,
        confidence=confidence,
        reason=reason,
        received_at=incident.received_at,
        road_references=refs,
        distance_m=_finite_or_none(result.distance_m),
        heading_deg=_finite_or_none(result.heading_deg),
        bearing_deg=_finite_or_none(result.bearing_deg),
        verified_geocode_source=evidence.source,
    )


def _finite_or_none(value: float | None) -> float | None:
    """Avoid propagating non-finite metrics to a future JSON renderer."""

    return value if value is not None and math.isfinite(value) else None


def existing_gps_fix(
    point: GeoPoint,
    observed_at: datetime,
    accuracy_m: float,
) -> VehicleFix:
    """Adapt already-published GPS values without reading any GPS device."""

    return VehicleFix(point, observed_at, accuracy_m)
