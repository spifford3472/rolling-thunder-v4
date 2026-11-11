"""Extract bounded, unverified road references from classified MeshCore traffic.

This module performs no geocoding, GPS polling, map matching, persistence,
network access or notifications. Returned text is evidence, never coordinates
or proof of a hazard. Ambiguous references explicitly fail closed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from rolling_thunder.meshcore_incident_classification import ClassifiedIncident, IncidentCategory

# Route terms require an explicit recognized prefix. Naked road numbers are
# never interpreted as highways, and county routes are not guessed to be SRs.
_ROUTE = re.compile(
    r"\b(?P<prefix>I|Interstate|US|U\.S\.|SR|State\s+Route|"
    r"State\s+Road|Route)\s*[- ]?\s*(?P<number>\d{1,4})\b",
    re.IGNORECASE,
)
_EXIT = re.compile(r"\b(?:exit|exits)\s+(?P<number>\d{1,3}[A-Z]?)\b", re.IGNORECASE)
_MILE = re.compile(
    r"\b(?:mile\s*(?:marker|post)|mm)\s*#?\s*(?P<number>\d{1,3}"
    r"(?:\.\d{1,2})?)\b",
    re.IGNORECASE,
)
_DIRECTION = re.compile(
    r"\b(?P<direction>northbound|southbound|eastbound|westbound|NB|SB|EB|WB)\b",
    re.IGNORECASE,
)
# A mention of a crossing is not a verified geospatial junction.
_JUNCTION = re.compile(r"\b(?:at|near|by|junction|intersection|with|and|&)\b", re.IGNORECASE)
_MAX_LENGTH = 512
_MAX_REFERENCES = 5


class ReferenceQuality(StrEnum):
    """How useful the reported text may be for later controlled lookup."""

    INSUFFICIENT = "insufficient"
    AMBIGUOUS = "ambiguous"
    SPECIFIC_UNVERIFIED = "specific_unverified"


@dataclass(frozen=True, slots=True)
class TrafficGeoreference:
    """Unverified extracted roadway facts, with explicit provenance limits."""

    roads: tuple[str, ...]
    exits: tuple[str, ...]
    mile_markers: tuple[str, ...]
    directions: tuple[str, ...]
    junction_mentioned: bool
    quality: ReferenceQuality
    reason: str

    @property
    def lookup_eligible(self) -> bool:
        """Allow later *review* of geocoding, never authorize a network call."""

        return self.quality == ReferenceQuality.SPECIFIC_UNVERIFIED


def _distinct(values: list[str]) -> tuple[str, ...]:
    """Deduplicate without reordering evidence, bounding the result size."""

    return tuple(dict.fromkeys(values))


def extract_traffic_georeference(
    incident: ClassifiedIncident,
) -> TrafficGeoreference:
    """Extract road/exit/mile/direction evidence from validated traffic text.

    Fail closed for stale inputs, conflicting roads/exits/directions or
    insufficient localization. A single road+exit or road+mile marker offers
    a potential geocoder *query*, but never a verified point or route match.
    The report still requires a trusted regional context and corroboration.
    """

    text = incident.text
    if (
        incident.channel_kind != "traffic"
        or incident.category == IncidentCategory.UNKNOWN
        or not text
        or len(text) > _MAX_LENGTH
    ):
        return TrafficGeoreference(
            (),
            (),
            (),
            (),
            False,
            ReferenceQuality.INSUFFICIENT,
            "not_a_bounded_classified_traffic_message",
        )
    roads: list[str] = []
    for match in _ROUTE.finditer(text):
        raw = match.group("prefix").upper().replace(".", "").replace(" ", "")
        canonical = (
            "I"
            if raw in {"I", "INTERSTATE"}
            else "US"
            if raw == "US"
            else "SR"
            if raw in {"SR", "STATEROUTE", "STATEROAD"}
            else "ROUTE"
        )
        roads.append(f"{canonical}-{int(match.group('number'))}")
    exits = _distinct([m.group("number").upper() for m in _EXIT.finditer(text)])
    miles = _distinct([m.group("number") for m in _MILE.finditer(text)])
    directions = _distinct(
        [
            {
                "NB": "N",
                "NORTHBOUND": "N",
                "SB": "S",
                "SOUTHBOUND": "S",
                "EB": "E",
                "EASTBOUND": "E",
                "WB": "W",
                "WESTBOUND": "W",
            }[m.group("direction").upper()]
            for m in _DIRECTION.finditer(text)
        ]
    )
    roads_found = _distinct(roads)
    junction = len(roads_found) > 1 and bool(_JUNCTION.search(text))
    if (
        len(roads_found) > _MAX_REFERENCES
        or len(exits) > 1
        or len(miles) > 1
        or len(directions) > 1
        or len(roads_found) > 1
    ):
        quality, reason = ReferenceQuality.AMBIGUOUS, "multiple_or_conflicting_references"
    elif len(roads_found) == 1 and (len(exits) == 1 or len(miles) == 1):
        quality = ReferenceQuality.SPECIFIC_UNVERIFIED
        reason = "road_and_exit_or_mile_marker_without_verified_location"
    else:
        quality, reason = ReferenceQuality.INSUFFICIENT, "insufficient_road_localization"
    return TrafficGeoreference(
        roads_found[:_MAX_REFERENCES],
        exits,
        miles,
        directions,
        junction,
        quality,
        reason,
    )
