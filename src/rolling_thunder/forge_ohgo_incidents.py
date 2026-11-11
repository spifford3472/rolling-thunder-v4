"""Safe OHGO incident intake, retention, and provider-isolated fetching.

The Ohio DOT API is not an incident verification or a routing engine. This
service is opt-in, never logs or returns the API key, and makes no calls when
disabled. The source transport is injected for deterministic, offline tests.
"""

from __future__ import annotations

import json
import math
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from rolling_thunder.meshcore_geographic_relevance import GeoPoint

_API_URL = "https://publicapi.ohgo.com/api/v1/incidents"
_MAX_ITEMS = 100
_MAX_BODY = 2_000_000
_MAX_FIELD = 180
_REGION = frozenset(
    {
        "akron",
        "cincinnati",
        "cleveland",
        "columbus",
        "dayton",
        "toledo",
        "central-ohio",
        "ne-ohio",
        "nw-ohio",
        "se-ohio",
        "sw-ohio",
    }
)


class OhgoState(StrEnum):
    """Explicit availability, never an implied empty incident list."""

    DISABLED = "disabled"
    UNAVAILABLE = "unavailable"
    CURRENT = "current"
    STALE = "stale"


@dataclass(frozen=True, slots=True)
class OhioIncident:
    """Bounded, provider-attributed incident marker, not a verified hazard."""

    incident_id: str
    point: GeoPoint
    route: str
    direction: str
    category: str
    description: str
    location: str
    road_status: str


@dataclass(frozen=True, slots=True)
class OhioIncidentSnapshot:
    """Immutable source status, suitable for a read-only presentation layer."""

    state: OhgoState
    incidents: tuple[OhioIncident, ...] = ()
    fetched_at: datetime | None = None
    source: str = "Ohio DOT OHGO"
    reason: str = "not_configured"

    @property
    def eligible_for_display(self) -> bool:
        """Fail closed on stale data; never interpret it as a confirmed road block."""

        return self.state == OhgoState.CURRENT


class OhgoProtocolError(ValueError):
    """Reject untrusted provider or response metadata."""


def _plain_string(value: object, *, maximum: int = _MAX_FIELD) -> str:
    """Normalize printable provider strings without leaking control sequences."""

    if not isinstance(value, str):
        return ""
    return "".join(ch for ch in value if ch.isprintable()).strip()[:maximum]


def _ohgo_field(record: dict[str, object], field: str) -> object:
    """Read canonical OHGO PascalCase or observed camelCase JSON names.

    OHGO's documented model uses PascalCase, but live JSON serialization
    begins with lowercase letters. Reject contradictory duplicate spellings.
    """

    alternate = field[0].lower() + field[1:]
    if field in record and alternate in record and record[field] != record[alternate]:
        raise OhgoProtocolError("Conflicting OHGO field aliases")
    return record.get(alternate, record.get(field))


def parse_ohgo_incidents(
    body: bytes, *, received_at: datetime, limit: int = _MAX_ITEMS
) -> OhioIncidentSnapshot:
    """Parse one complete OHGO v1 result envelope, rejecting failed filters.

    A partial result page is deliberately rejected instead of masquerading
    as the statewide/current total. UI displays source statements as reports,
    never asserts that an OHGO item is a verified vehicle hazard.
    """

    if not 1 <= limit <= _MAX_ITEMS or len(body) > _MAX_BODY:
        raise OhgoProtocolError("Unsafe OHGO page bounds")
    if received_at.utcoffset() is None:
        raise OhgoProtocolError("Naive response timestamp")
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, ValueError) as exc:
        raise OhgoProtocolError("Malformed OHGO JSON") from exc
    if not isinstance(payload, dict):
        raise OhgoProtocolError("Unexpected OHGO result")
    rejected = _ohgo_field(payload, "RejectedFilters")
    if not isinstance(rejected, list):
        raise OhgoProtocolError("OHGO rejected-filter status absent")
    if rejected:
        raise OhgoProtocolError("OHGO rejected requested region filter")
    rows = _ohgo_field(payload, "Results")
    if not isinstance(rows, list):
        raise OhgoProtocolError("OHGO result list absent")
    # A missing or incorrect count is not evidence of an empty, complete page.
    pages = _ohgo_field(payload, "TotalPageCount")
    count = _ohgo_field(payload, "CurrentResultCount")
    total = _ohgo_field(payload, "TotalResultCount")
    if (
        type(pages) is not int
        or pages not in (0, 1)
        or (pages == 0 and len(rows) != 0)
        or type(count) is not int
        or count != len(rows)
        or type(total) is not int
        or total != len(rows)
        or len(rows) > limit
    ):
        raise OhgoProtocolError("OHGO response truncated or paginated")
    results: list[OhioIncident] = []
    known: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        incident_id = _plain_string(_ohgo_field(row, "Id"), maximum=96)
        if not incident_id or incident_id in known:
            continue
        try:
            lat = _ohgo_field(row, "Latitude")
            lon = _ohgo_field(row, "Longitude")
            if (
                not isinstance(lat, (float, int))
                or not isinstance(lon, (float, int))
                or isinstance(lat, bool)
                or isinstance(lon, bool)
            ):
                continue
            point = GeoPoint(float(lat), float(lon))
        except (KeyError, TypeError, ValueError):
            continue
        known.add(incident_id)
        results.append(
            OhioIncident(
                incident_id=incident_id,
                point=point,
                route=_plain_string(_ohgo_field(row, "RouteName")),
                direction=_plain_string(_ohgo_field(row, "Direction"), maximum=32),
                category=_plain_string(_ohgo_field(row, "Category"), maximum=64),
                description=_plain_string(_ohgo_field(row, "Description")),
                location=_plain_string(_ohgo_field(row, "Location")),
                road_status=_plain_string(_ohgo_field(row, "RoadStatus"), maximum=64),
            )
        )
    return OhioIncidentSnapshot(
        OhgoState.CURRENT,
        tuple(results),
        received_at.astimezone(UTC),
        reason="ok",
    )


@dataclass(frozen=True, slots=True)
class OhgoResponse:
    """Transport-neutral HTTP response; headers are normalized lower-case."""

    status: int
    body: bytes
    headers: Mapping[str, str]


OhgoTransport = Callable[[str, Mapping[str, str], float], OhgoResponse]


class ForgeOhgoIncidentProvider:
    """An opt-in rate-limited client; no external calls without a valid key."""

    def __init__(
        self,
        *,
        transport: OhgoTransport,
        api_key: str | None = None,
        region: str = "sw-ohio",
        enabled: bool = False,
        clock: Callable[[], float] = time.monotonic,
        minimum_interval_s: float = 120.0,
    ) -> None:
        if region not in _REGION:
            raise ValueError("Unsupported OHGO region")
        if not math.isfinite(minimum_interval_s) or minimum_interval_s < 60:
            raise ValueError("Unsafe OHGO refresh interval")
        self._transport = transport
        self._key = api_key if api_key and api_key.strip() else None
        self._enabled = enabled
        self._region = region
        self._clock = clock
        self._interval = minimum_interval_s
        self._last_attempt: float | None = None
        self._etag: str | None = None
        self._snapshot = OhioIncidentSnapshot(OhgoState.DISABLED)
        self._max_age = timedelta(minutes=5)

    @property
    def snapshot(self) -> OhioIncidentSnapshot:
        """Return the latest response without provider I/O."""

        return self._snapshot

    def refresh(self, now: datetime) -> OhioIncidentSnapshot:
        """Fetch only when enabled and due; preserve stale/error status."""

        if now.utcoffset() is None:
            raise ValueError("Naive refresh time")
        if not self._enabled or self._key is None:
            self._snapshot = OhioIncidentSnapshot(
                OhgoState.DISABLED, reason="api_key_not_configured"
            )
            return self._snapshot
        tick = self._clock()
        if not math.isfinite(tick):
            return self._snapshot
        if self._last_attempt is not None and tick - self._last_attempt < self._interval:
            return self._current_or_stale(now)
        self._last_attempt = tick
        headers = {"Authorization": f"APIKEY {self._key}", "Accept": "application/json"}
        if self._etag and re.fullmatch(r'[\w"\-]+', self._etag):
            headers["If-None-Match"] = self._etag
        try:
            result = self._transport(
                f"{_API_URL}?region={self._region}&page-size={_MAX_ITEMS}",
                headers,
                4.0,
            )
            if result.status == 304 and self._snapshot.fetched_at is not None:
                self._snapshot = OhioIncidentSnapshot(
                    OhgoState.CURRENT,
                    self._snapshot.incidents,
                    now.astimezone(UTC),
                    reason="not_modified",
                )
            elif result.status == 200:
                parsed = parse_ohgo_incidents(result.body, received_at=now)
                self._snapshot = parsed
                self._etag = result.headers.get("etag")
            else:
                self._snapshot = OhioIncidentSnapshot(
                    OhgoState.UNAVAILABLE,
                    reason="upstream_error",
                )
        except (OSError, TimeoutError, OhgoProtocolError, ValueError):
            self._snapshot = OhioIncidentSnapshot(
                OhgoState.UNAVAILABLE,
                reason="upstream_unavailable",
            )
        return self._snapshot

    def _current_or_stale(self, now: datetime) -> OhioIncidentSnapshot:
        current = self._snapshot
        if (
            current.fetched_at is not None
            and now.astimezone(UTC) - current.fetched_at > self._max_age
        ):
            self._snapshot = OhioIncidentSnapshot(
                OhgoState.STALE,
                current.incidents,
                current.fetched_at,
                reason="snapshot_expired",
            )
        return self._snapshot
