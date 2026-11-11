"""Traffic relevance is offline, evidence-gated and never a driver alert."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from rolling_thunder.meshcore_geographic_relevance import (
    GeoPoint,
    PublishedGpsHeading,
    Relevance,
    VehicleFix,
)
from rolling_thunder.meshcore_incident_classification import (
    ClassifiedIncident,
    PublicChannelPolicy,
    PublicMessage,
    classify_public_message,
)
from rolling_thunder.meshcore_traffic_relevance import (
    AssessmentConfidence,
    GeographicEvidence,
    assess_traffic_candidate,
)

NOW = datetime(2026, 11, 11, 16, 0, tzinfo=UTC)
POLICY = PublicChannelPolicy(frozenset({"1:#traffic"}), frozenset({"skywarn"}))
SITE = GeoPoint(39.56, -84.10)
BASE = GeoPoint(39.54, -84.10)


def _incident(
    text: str = "Crash on I-75 northbound near Exit 44",
    *,
    received_at: datetime = NOW - timedelta(minutes=2),
    channel: str = "1:#traffic",
) -> ClassifiedIncident:
    result = classify_public_message(
        PublicMessage(channel, "unverified", text, received_at),
        POLICY,
    )
    assert result is not None
    return result


def _history(
    now: datetime = NOW,
    *,
    speed: float | None = 15.0,
    course: float | None = 0.0,
    accuracy: float = 5.0,
    second: bool = True,
) -> PublishedGpsHeading:
    history = PublishedGpsHeading()
    assert history.offer(VehicleFix(BASE, now - timedelta(seconds=3), accuracy, speed, course))
    if second:
        assert history.offer(VehicleFix(BASE, now, accuracy, speed, course))
    return history


def _evidence(
    *,
    point: GeoPoint = SITE,
    road: str = "I-75",
    exit_or_mile: str = "44",
    source: str = "reviewed-geodata",
    specific: bool = True,
    alignment: bool = False,
    direction: str | None = None,
    checked: datetime = NOW,
) -> GeographicEvidence:
    return GeographicEvidence(
        point,
        road,
        exit_or_mile,
        checked,
        source,
        specific,
        alignment,
        direction,
    )


def test_complete_evidence_still_never_authorizes_alert() -> None:
    result = assess_traffic_candidate(
        _incident(),
        _history(),
        NOW,
        evidence=_evidence(alignment=True, direction="N"),
    )
    assert result.relevance == Relevance.AHEAD_CONFIRMED
    assert result.confidence == AssessmentConfidence.MODERATE
    assert result.reason == "independent_route_alignment_and_site_evidence"
    assert result.verified_geocode_source == "reviewed-geodata"
    assert result.distance_m is not None
    assert not result.is_verified_incident
    assert not result.driver_alert_permitted


def test_heading_alone_cannot_confirm_route() -> None:
    for evidence in (
        _evidence(),
        _evidence(alignment=True),
        _evidence(alignment=True, direction="S"),
    ):
        result = assess_traffic_candidate(
            _incident(),
            _history(),
            NOW,
            evidence=evidence,
        )
        assert result.relevance == Relevance.POSSIBLY_AHEAD
        assert result.confidence == AssessmentConfidence.LOW
        assert not result.driver_alert_permitted


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"evidence": None}, "no_independently_verified_geographic_evidence"),
        (
            {"evidence": _evidence(specific=False)},
            "geocode_is_generic_road_not_incident_site",
        ),
        ({"evidence": _evidence(road="I-71")}, "geocode_road_mismatch"),
        ({"evidence": _evidence(exit_or_mile="42")}, "geocode_exit_or_mile_mismatch"),
        (
            {"evidence": _evidence(checked=NOW - timedelta(days=8))},
            "geographic_evidence_stale_or_future",
        ),
        (
            {"evidence": _evidence(checked=NOW + timedelta(seconds=1))},
            "geographic_evidence_stale_or_future",
        ),
    ],
)
def test_bad_or_missing_geographic_evidence_is_unknown(
    kwargs: dict[str, GeographicEvidence | None],
    reason: str,
) -> None:
    result = assess_traffic_candidate(_incident(), _history(), NOW, **kwargs)
    assert result.relevance == Relevance.INSUFFICIENT
    assert result.reason == reason
    assert not result.driver_alert_permitted


@pytest.mark.parametrize(
    "received_at",
    [NOW - timedelta(minutes=11), NOW + timedelta(seconds=1)],
)
def test_aged_or_future_report_is_not_an_incident_location(
    received_at: datetime,
) -> None:
    result = assess_traffic_candidate(
        _incident(received_at=received_at),
        _history(),
        NOW,
        evidence=_evidence(alignment=True, direction="N"),
    )
    assert result.reason == "report_outside_analysis_freshness_window"


@pytest.mark.parametrize(
    "text",
    [
        "Crash I-75 and I-71 near Exit 44",
        "Crash I-75 near Exit 44 or Exit 45",
        "Crash on I-75 NB or SB Exit 44",
        "Crash I-75 northbound",
    ],
)
def test_ambiguous_and_underspecified_reports_fail_closed(text: str) -> None:
    result = assess_traffic_candidate(
        _incident(text),
        _history(),
        NOW,
        evidence=_evidence(),
    )
    assert result.reason == "insufficient_or_ambiguous_report_location"


def test_no_unclassified_message_promoted_to_incident() -> None:
    result = assess_traffic_candidate(
        _incident("I-75 NB Exit 44"),
        _history(),
        NOW,
        evidence=_evidence(),
    )
    assert result.reason == "no_classified_public_traffic_incident"


def test_no_weather_channel_crossover() -> None:
    result = assess_traffic_candidate(
        _incident("Flooding I-75 NB Exit 44", channel="skywarn"),
        _history(),
        NOW,
        evidence=_evidence(),
    )
    assert result.relevance == Relevance.INSUFFICIENT


def test_stale_gps_and_inaccurate_gps_fail_closed() -> None:
    assert (
        assess_traffic_candidate(
            _incident(),
            _history(now=NOW - timedelta(seconds=30)),
            NOW,
            evidence=_evidence(),
        ).reason
        == "no_fresh_existing_gps"
    )
    assert (
        assess_traffic_candidate(
            _incident(),
            _history(accuracy=100),
            NOW,
            evidence=_evidence(),
        ).reason
        == "gps_accuracy_insufficient"
    )


def test_multiple_gps_samples_required_even_with_speed_course() -> None:
    result = assess_traffic_candidate(
        _incident(),
        _history(second=False),
        NOW,
        evidence=_evidence(),
    )
    assert result.reason == "insufficient_gps_sample_history"


def test_stationary_returns_route_unknown() -> None:
    result = assess_traffic_candidate(
        _incident(),
        _history(speed=0),
        NOW,
        evidence=_evidence(alignment=True, direction="N"),
    )
    assert result.relevance == Relevance.NEARBY_ROUTE_UNKNOWN


def test_away_and_far_from_site_remain_non_alerting() -> None:
    away = assess_traffic_candidate(
        _incident(),
        _history(course=180),
        NOW,
        evidence=_evidence(),
    )
    assert away.relevance == Relevance.BEHIND
    far = assess_traffic_candidate(
        _incident(),
        _history(),
        NOW,
        evidence=_evidence(point=GeoPoint(40.4, -84.1)),
    )
    assert far.relevance == Relevance.NOT_RELEVANT
    assert not away.driver_alert_permitted
    assert not far.driver_alert_permitted


def test_invalid_unverified_geocoding_metadata_rejected() -> None:
    with pytest.raises(ValueError):
        _evidence(direction="northbound")
    with pytest.raises(ValueError):
        _evidence(checked=NOW.replace(tzinfo=None))
    with pytest.raises(ValueError):
        assess_traffic_candidate(_incident(), _history(), NOW.replace(tzinfo=None))


def test_injected_gps_history_uses_no_second_receiver() -> None:
    history = _history(speed=None, course=None)
    assert history.has_recent_span(NOW)
    assert history.heading(NOW) is None
    result = assess_traffic_candidate(_incident(), history, NOW, evidence=_evidence())
    assert result.relevance == Relevance.NEARBY_ROUTE_UNKNOWN
