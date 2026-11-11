"""Hardware-free privacy, allowlist, and incident classification tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from rolling_thunder.meshcore_incident_classification import (
    IncidentCategory,
    PublicChannelPolicy,
    PublicMessage,
    classify_public_message,
)


POLICY = PublicChannelPolicy(
    traffic_ids=frozenset({"public-traffic-01"}),
    skywarn_ids=frozenset({"public-skywarn-02"}),
)
NOW = datetime(2026, 11, 11, 14, 0, tzinfo=UTC)


def _message(
    text: str, channel: str = "public-traffic-01", sender: str = "node-1"
) -> PublicMessage:
    return PublicMessage(channel, sender, text, NOW)


@pytest.mark.parametrize(
    ("text", "category"),
    [
        ("Accident I-71 southbound exit 28", IncidentCategory.ACCIDENT),
        ("Construction US 42 at the bridge", IncidentCategory.CONSTRUCTION),
        ("Road closed SR 73", IncidentCategory.CLOSURE),
        ("Heavy congestion on I 75", IncidentCategory.CONGESTION),
        ("Disabled vehicle I-71 NB", IncidentCategory.DISABLED_VEHICLE),
        ("Debris on Route 48", IncidentCategory.ROAD_DEBRIS),
        ("Icy road on US-35", IncidentCategory.HAZARDOUS_ROAD),
        ("Clear road ahead", IncidentCategory.UNKNOWN),
        ("Crsh on 71", IncidentCategory.UNKNOWN),
        ("Accident near a city without a highway", IncidentCategory.ACCIDENT),
    ],
)
def test_traffic_rules(text: str, category: IncidentCategory) -> None:
    result = classify_public_message(_message(text), POLICY)
    assert result is not None
    assert result.category == category
    assert result.geographic_confidence == "unknown"
    assert result.channel_kind == "traffic"


@pytest.mark.parametrize(
    ("text", "category"),
    [
        ("Tornado reported near town", IncidentCategory.TORNADO),
        ("Funnel cloud", IncidentCategory.TORNADO),
        ("Flooding at bridge", IncidentCategory.FLOODING),
        ("Hail at park", IncidentCategory.HAIL),
        ("Severe thunderstorm near county line", IncidentCategory.THUNDERSTORM),
        ("High winds today", IncidentCategory.HIGH_WINDS),
        ("Heavy rain without location", IncidentCategory.HEAVY_RAIN),
        ("Weather check-in", IncidentCategory.UNKNOWN),
    ],
)
def test_skywarn_rules(text: str, category: IncidentCategory) -> None:
    result = classify_public_message(
        _message(text, channel="public-skywarn-02"), POLICY
    )
    assert result is not None
    assert result.category == category
    assert result.channel_kind == "skywarn"


def test_road_and_direction_do_not_imply_geocoding() -> None:
    result = classify_public_message(
        _message("Accident I-71 southbound near exit 28"), POLICY
    )
    assert result is not None
    assert result.road == "I-71"
    assert result.travel_direction == "SOUTHBOUND"
    assert result.exit == "exit 28"
    assert result.geographic_confidence == "unknown"


@pytest.mark.parametrize(
    "bad",
    [
        PublicMessage("public-traffic-01", "node", "", NOW),
        PublicMessage("public-traffic-01", "node", "x" * 513, NOW),
        PublicMessage("public-traffic-01", "", "Accident", NOW),
        PublicMessage("public-traffic-01", "node", "Crash\x00", NOW),
        PublicMessage("public-traffic-01", "node", "Crash", datetime(2026, 11, 11)),
        PublicMessage("not-authorized", "node", "Crash", NOW),
        PublicMessage("#traffic", "node", "Crash", NOW),
    ],
)
def test_rejects_untrusted_or_unsupported_input(bad: PublicMessage) -> None:
    assert classify_public_message(bad, POLICY) is None


def test_public_channel_policy_rejects_overlap_and_empty() -> None:
    with pytest.raises(ValueError):
        PublicChannelPolicy(frozenset({"same"}), frozenset({"same"}))
    with pytest.raises(ValueError):
        PublicChannelPolicy(frozenset(), frozenset({"skywarn"}))


def test_no_cross_channel_weather_category() -> None:
    result = classify_public_message(_message("Tornado"), POLICY)
    assert result is not None
    assert result.category == IncidentCategory.UNKNOWN
