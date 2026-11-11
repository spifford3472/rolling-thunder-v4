"""Pure, bounded classification of explicitly approved public MeshCore channel text.

This module neither listens to the serial device nor persists raw content.
A separate, privacy-reviewed intake must verify the physical channel identity
before supplying public text. No transmit or subscription authority is granted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


_MAX_MESSAGE_LENGTH = 512
_MAX_SENDER_LENGTH = 128
_TOKEN_RE = re.compile(r"\b(?:accident|crash|collision|wreck|construction|roadwork|"
                       r"closure|closed|blocked|congestion|traffic jam|backup|"
                       r"disabled vehicle|stalled vehicle|debris|icy|ice|"
                       r"thunderstorm|tornado|funnel cloud|flooding|flooded|"
                       r"hail|high winds|strong winds|heavy rain|downpour)\b", re.I)
_ROAD_RE = re.compile(
    r"\b(?:I[- ]?\d{1,3}|US[- ]?\d{1,3}|SR[- ]?\d{1,4}|"
    r"Route\s+\d{1,4})\b", re.I
)
_DIRECTION_RE = re.compile(r"\b(northbound|southbound|eastbound|westbound|"
                            r"NB|SB|EB|WB)\b", re.I)
_EXIT_RE = re.compile(r"\bexit\s+\d{1,3}[a-z]?\b", re.I)


class IncidentCategory(StrEnum):
    """Supported unverified report classifications."""

    ACCIDENT = "accident"
    CONSTRUCTION = "construction"
    CLOSURE = "closure"
    CONGESTION = "congestion"
    DISABLED_VEHICLE = "disabled_vehicle"
    ROAD_DEBRIS = "road_debris"
    HAZARDOUS_ROAD = "hazardous_road"
    THUNDERSTORM = "thunderstorm"
    TORNADO = "tornado"
    FLOODING = "flooding"
    HAIL = "hail"
    HIGH_WINDS = "high_winds"
    HEAVY_RAIN = "heavy_rain"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class PublicChannelPolicy:
    """Exact configured channel identifiers, not display names or substrings."""

    traffic_ids: frozenset[str]
    skywarn_ids: frozenset[str]

    def __post_init__(self) -> None:
        if not self.traffic_ids or not self.skywarn_ids:
            raise ValueError("Both public-channel allowlists are required")
        if self.traffic_ids & self.skywarn_ids:
            raise ValueError("A channel cannot have conflicting classifications")
        if any(not value or len(value) > 128 for value in
               self.traffic_ids | self.skywarn_ids):
            raise ValueError("Invalid channel identifier")


@dataclass(frozen=True, slots=True)
class PublicMessage:
    """Validated public-channel input; intake must enforce provenance."""

    channel_id: str
    sender: str
    text: str
    received_at: datetime


@dataclass(frozen=True, slots=True)
class ClassifiedIncident:
    """Unverified incident candidate; no geographic or route claims."""

    category: IncidentCategory
    channel_kind: str
    sender: str
    text: str
    received_at: datetime
    road: str | None
    travel_direction: str | None
    exit: str | None
    classification_confidence: str
    geographic_confidence: str = "unknown"


_TRAFFIC_RULES: tuple[tuple[IncidentCategory, re.Pattern[str]], ...] = tuple(
    (category, re.compile(pattern, re.I)) for category, pattern in (
        (IncidentCategory.ACCIDENT, r"\b(?:accident|crash|collision|wreck)\b"),
        (IncidentCategory.CLOSURE, r"\b(?:closed|closure|blocked)\b"),
        (IncidentCategory.CONSTRUCTION, r"\b(?:construction|roadwork)\b"),
        (IncidentCategory.DISABLED_VEHICLE,
         r"\b(?:disabled vehicle|stalled vehicle)\b"),
        (IncidentCategory.ROAD_DEBRIS, r"\bdebris\b"),
        (IncidentCategory.HAZARDOUS_ROAD, r"\b(?:icy|ice)\b"),
        (IncidentCategory.CONGESTION, r"\b(?:congestion|traffic jam|backup)\b"),
    )
)
_WEATHER_RULES: tuple[tuple[IncidentCategory, re.Pattern[str]], ...] = tuple(
    (category, re.compile(pattern, re.I)) for category, pattern in (
        (IncidentCategory.TORNADO, r"\b(?:tornado|funnel cloud)\b"),
        (IncidentCategory.FLOODING, r"\b(?:flooding|flooded)\b"),
        (IncidentCategory.HAIL, r"\bhail\b"),
        (IncidentCategory.THUNDERSTORM, r"\bthunderstorm\b"),
        (IncidentCategory.HIGH_WINDS, r"\b(?:high winds|strong winds)\b"),
        (IncidentCategory.HEAVY_RAIN, r"\b(?:heavy rain|downpour)\b"),
    )
)


def classify_public_message(
    message: PublicMessage, policy: PublicChannelPolicy
) -> ClassifiedIncident | None:
    """Classify allowed public text without I/O, AI, or inferred location.

    Return None for unsupported channels or invalid provenance. Text without an
    event keyword is retained as UNKNOWN by callers, not asserted as a hazard.
    """
    if message.channel_id in policy.traffic_ids:
        kind, rules = "traffic", _TRAFFIC_RULES
    elif message.channel_id in policy.skywarn_ids:
        kind, rules = "skywarn", _WEATHER_RULES
    else:
        return None

    if (
        message.received_at.tzinfo is None
        or message.received_at.utcoffset() is None
        or len(message.text) > _MAX_MESSAGE_LENGTH
        or not message.text.strip()
        or len(message.sender) > _MAX_SENDER_LENGTH
        or not message.sender.strip()
        or "\x00" in message.text
    ):
        return None

    normalized = " ".join(message.text.split())
    category = IncidentCategory.UNKNOWN
    for candidate, pattern in rules:
        if pattern.search(normalized):
            category = candidate
            break

    road_match = _ROAD_RE.search(normalized)
    direction_match = _DIRECTION_RE.search(normalized)
    exit_match = _EXIT_RE.search(normalized)
    # Observing a road name is not a geocoded point or verified vehicle route.
    direction = direction_match.group(0).upper() if direction_match else None
    return ClassifiedIncident(
        category=category,
        channel_kind=kind,
        sender=message.sender.strip(),
        text=normalized,
        received_at=message.received_at.astimezone(UTC),
        road=road_match.group(0).upper() if road_match else None,
        travel_direction=direction,
        exit=exit_match.group(0) if exit_match else None,
        classification_confidence="rule_match" if category != IncidentCategory.UNKNOWN
        else "unclassified",
    )
