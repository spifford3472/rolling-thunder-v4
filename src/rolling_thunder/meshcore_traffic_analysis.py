"""Optional analysis-only coordinator for already-classified public traffic.

This is not composed into the live broker worker, dashboard or SCOUT. It
requires a separately authorized provider and never signals a driver.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from rolling_thunder.meshcore_geographic_relevance import PublishedGpsHeading
from rolling_thunder.meshcore_incident_classification import (
    ClassifiedIncident,
    IncidentCategory,
)
from rolling_thunder.meshcore_traffic_geocoding import (
    ApprovedTrafficGeocoder,
    request_for_reference,
)
from rolling_thunder.meshcore_traffic_georeferences import extract_traffic_georeference
from rolling_thunder.meshcore_traffic_relevance import (
    TrafficRelevanceDecision,
    assess_traffic_candidate,
)


def analyze_traffic(
    incident: ClassifiedIncident,
    history: PublishedGpsHeading,
    now: datetime,
    *,
    region: str,
    geocoder: ApprovedTrafficGeocoder,
) -> TrafficRelevanceDecision:
    """Use existing GPS and an explicit provider only when evidence suffices.

    An expired, unknown, geographically ambiguous or poor-GPS incident never
    triggers an external lookup. The resolver is disabled by default and its
    output is never a verified report or authorization to notify.
    """

    # Existing unknown/ambiguous/future/expired traffic messages are handled
    # without attempting geocoding or any additional GPS sampling.
    preflight = assess_traffic_candidate(incident, history, now)
    if preflight.reason != "no_independently_verified_geographic_evidence":
        return preflight
    if incident.category == IncidentCategory.UNKNOWN:
        return preflight
    if (
        not timedelta(0)
        <= now.astimezone(UTC) - incident.received_at.astimezone(UTC)
        <= timedelta(minutes=10)
    ):
        return preflight
    fix = history.latest(now)
    if fix is None or fix.accuracy_m > 30.0 or not history.has_recent_span(now):
        return assess_traffic_candidate(incident, history, now)
    reference = extract_traffic_georeference(incident)
    query = request_for_reference(reference, region=region)
    if query is None:
        return preflight
    evidence = geocoder.resolve(query, now=now)
    return assess_traffic_candidate(incident, history, now, evidence=evidence)
