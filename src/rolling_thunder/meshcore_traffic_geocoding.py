"""Explicitly gated and cached provider-neutral traffic geocoding adapter.

Only a separately selected/approved Forge provider may implement the injected
lookup function. This module has no HTTP client or default provider. A highway
centroid, ambiguous result or coordinate without roadway/exit evidence is
rejected. Never run public Nominatim as a periodic background bulk service.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from rolling_thunder.meshcore_geographic_relevance import GeoPoint
from rolling_thunder.meshcore_traffic_georeferences import (
    ReferenceQuality,
    TrafficGeoreference,
)
from rolling_thunder.meshcore_traffic_relevance import GeographicEvidence


@dataclass(frozen=True, slots=True)
class TrafficGeocodeRequest:
    """Non-sensitive canonical road/site reference and explicit region."""

    road: str
    exit_or_mile: str
    region: str

    def __post_init__(self) -> None:
        if (
            not self.road
            or not self.exit_or_mile
            or not self.region.strip()
            or len(self.road) > 32
            or len(self.exit_or_mile) > 24
            or len(self.region) > 80
        ):
            raise ValueError("Invalid bounded traffic geocoding request")


@dataclass(frozen=True, slots=True)
class TrafficGeocodeResult:
    """Provider-specific result must assert exact site and route attestation."""

    latitude: float
    longitude: float
    road: str
    exit_or_mile: str
    source: str
    point_specific: bool
    route_alignment_verified: bool = False
    direction_verified: str | None = None


def request_for_reference(
    reference: TrafficGeoreference, *, region: str
) -> TrafficGeocodeRequest | None:
    """Prepare lookup only for a unique road and matching landmark."""

    if (
        reference.quality != ReferenceQuality.SPECIFIC_UNVERIFIED
        or len(reference.roads) != 1
        or (len(reference.exits) + len(reference.mile_markers)) != 1
    ):
        return None
    landmark = (reference.exits + reference.mile_markers)[0]
    return TrafficGeocodeRequest(reference.roads[0], landmark, region)


class ApprovedTrafficGeocoder:
    """Single-flight bounded geocoding with disabled-by-default external calls.

    A cache hit does not authorize alerting. Calling an approved lookup is
    opt-in and cannot run more than once per 2 seconds or above a per-session
    budget; the caller must additionally follow the selected provider's policy.
    """

    def __init__(
        self,
        *,
        lookup: Callable[[TrafficGeocodeRequest], TrafficGeocodeResult | None],
        enabled: bool = False,
        maximum_queries: int = 10,
        minimum_interval_s: float = 2.0,
        ttl: timedelta = timedelta(days=1),
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not 0 <= maximum_queries <= 100:
            raise ValueError("Invalid query budget")
        if not math.isfinite(minimum_interval_s) or minimum_interval_s < 1:
            raise ValueError("Invalid provider interval")
        if not timedelta(seconds=1) <= ttl <= timedelta(days=7):
            raise ValueError("Invalid cache lifetime")
        self._lookup = lookup
        self._enabled = enabled
        self._maximum = maximum_queries
        self._interval = minimum_interval_s
        self._ttl = ttl
        self._clock = clock
        self._queries = 0
        self._last_query: float | None = None
        self._cache: dict[TrafficGeocodeRequest, GeographicEvidence | None] = {}
        self._expires: dict[TrafficGeocodeRequest, datetime] = {}

    def resolve(
        self, request: TrafficGeocodeRequest, *, now: datetime
    ) -> GeographicEvidence | None:
        """Return only exact, specific cached evidence or a safely bounded lookup."""

        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Lookup time must be timezone aware")
        utc_now = now.astimezone(UTC)
        if request in self._expires and utc_now <= self._expires[request]:
            return self._cache[request]
        if not self._enabled or self._queries >= self._maximum:
            return None
        monotonic_now = self._clock()
        if not math.isfinite(monotonic_now):
            return None
        if self._last_query is not None and monotonic_now - self._last_query < self._interval:
            return None

        # Count attempts and throttle even unsuccessful, timed-out requests.
        # Failures do not authorize repeated retry storms.
        self._last_query = monotonic_now
        self._queries += 1
        try:
            result = self._lookup(request)
        except (OSError, TimeoutError, ValueError):
            result = None
        evidence: GeographicEvidence | None = None
        if (
            result is not None
            and result.point_specific
            and result.road == request.road
            and result.exit_or_mile == request.exit_or_mile
        ):
            try:
                evidence = GeographicEvidence(
                    point=GeoPoint(result.latitude, result.longitude),
                    road=result.road,
                    exit_or_mile=result.exit_or_mile,
                    verified_at=utc_now,
                    source=result.source,
                    point_specific=True,
                    route_alignment_verified=result.route_alignment_verified,
                    direction_verified=result.direction_verified,
                )
            except ValueError:
                evidence = None
        self._cache[request] = evidence
        self._expires[request] = utc_now + self._ttl
        return evidence
