"""Pure traffic georeference extraction with fail-closed ambiguous reports."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from rolling_thunder.meshcore_incident_classification import (
    IncidentCategory,
    PublicChannelPolicy,
    PublicMessage,
    classify_public_message,
)
from rolling_thunder.meshcore_traffic_georeferences import (
    ReferenceQuality,
    extract_traffic_georeference,
)

NOW = datetime(2026, 11, 11, tzinfo=UTC)
POLICY = PublicChannelPolicy(frozenset({"traffic:1"}), frozenset({"skywarn:5"}))


def _classify(text: str, *, channel: str = "traffic:1"):
    incident = classify_public_message(
        PublicMessage(channel, "unverified", text, NOW),
        POLICY,
    )
    assert incident is not None
    return incident


def test_specific_exit_is_still_unverified_and_not_geocoded() -> None:
    result = extract_traffic_georeference(_classify("Crash on I-75 northbound near Exit 44"))
    assert result.roads == ("I-75",)
    assert result.directions == ("N",)
    assert result.exits == ("44",)
    assert result.mile_markers == ()
    assert result.quality == ReferenceQuality.SPECIFIC_UNVERIFIED
    assert result.lookup_eligible
    assert not hasattr(result, "latitude")
    assert not hasattr(result, "longitude")


@pytest.mark.parametrize(
    ("message", "road", "mile", "direction"),
    [
        ("Debris US 35 WB near mile marker 12.5", "US-35", "12.5", "W"),
        ("Construction SR-73 EB at mm 5", "SR-73", "5", "E"),
        ("Closure on Interstate 71 SB milepost 22", "I-71", "22", "S"),
        ("Crash on U.S. 42 northbound mile marker 2", "US-42", "2", "N"),
        ("Crash State Route 48 near Exit 9", "SR-48", "", ""),
    ],
)
def test_canonical_road_variants(
    message: str,
    road: str,
    mile: str,
    direction: str,
) -> None:
    result = extract_traffic_georeference(_classify(message))
    assert result.roads == (road,)
    if mile:
        assert result.mile_markers == (mile,)
    if direction:
        assert result.directions == (direction,)
    assert result.lookup_eligible


@pytest.mark.parametrize(
    "message",
    [
        "Crash I-75 near Exit 42 or Exit 44",
        "Crash I-75 NB or SB Exit 44",
        "Crash I-75 and I-71 near Exit 44",
        "Crash I-75 at mm 12 or mile marker 15",
    ],
)
def test_conflicting_references_reject_lookup(message: str) -> None:
    result = extract_traffic_georeference(_classify(message))
    assert result.quality == ReferenceQuality.AMBIGUOUS
    assert not result.lookup_eligible


@pytest.mark.parametrize(
    "message",
    [
        "Crash on 75 at exit 42",
        "Crash near Springfield",
        "Crash I-75 northbound",
        "Construction at exit 42",
        "Traffic jam on Route 4",
        "Crash at Exit 44 on ramp",
    ],
)
def test_insufficient_context_is_not_geocoded(message: str) -> None:
    result = extract_traffic_georeference(_classify(message))
    assert result.quality == ReferenceQuality.INSUFFICIENT
    assert not result.lookup_eligible


def test_geographic_extraction_requires_classified_traffic_provenance() -> None:
    skywarn = _classify("Flooding on I-75 Exit 44", channel="skywarn:5")
    result = extract_traffic_georeference(skywarn)
    assert result.quality == ReferenceQuality.INSUFFICIENT
    assert not result.roads


def test_unclassified_traffic_does_not_become_an_alert() -> None:
    incident = _classify("I-75 NB near Exit 44")
    assert incident.category == IncidentCategory.UNKNOWN
    # Extraction is evidence-only, never a promotion to an incident category.
    result = extract_traffic_georeference(incident)
    assert not result.lookup_eligible
    assert result.quality == ReferenceQuality.INSUFFICIENT
    assert incident.category == IncidentCategory.UNKNOWN


def test_junction_is_ambiguous_without_road_matching() -> None:
    result = extract_traffic_georeference(_classify("Crash I-75 at I-70 interchange Exit 61"))
    assert result.junction_mentioned
    assert result.quality == ReferenceQuality.AMBIGUOUS
