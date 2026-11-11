"""Coordinator regression: no provider calls when reports or GPS are unsafe."""

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
    PublicChannelPolicy,
    PublicMessage,
    classify_public_message,
)
from rolling_thunder.meshcore_traffic_analysis import analyze_traffic
from rolling_thunder.meshcore_traffic_geocoding import (
    ApprovedTrafficGeocoder,
    TrafficGeocodeRequest,
    TrafficGeocodeResult,
)

NOW = datetime(2026, 11, 11, 16, tzinfo=UTC)
POLICY = PublicChannelPolicy(frozenset({"1:#traffic"}), frozenset({"skywarn"}))


def _incident(text: str, *, timestamp: datetime = NOW - timedelta(seconds=30)):
    result = classify_public_message(
        PublicMessage("1:#traffic", "unverified", text, timestamp),
        POLICY,
    )
    assert result is not None
    return result


def _history(*, accuracy: float = 5) -> PublishedGpsHeading:
    history = PublishedGpsHeading()
    for seconds in (3, 0):
        history.offer(
            VehicleFix(
                GeoPoint(39.54, -84.1),
                NOW - timedelta(seconds=seconds),
                accuracy,
                15,
                0,
            )
        )
    return history


def _provider(calls: list[TrafficGeocodeRequest]) -> ApprovedTrafficGeocoder:
    def lookup(req: TrafficGeocodeRequest) -> TrafficGeocodeResult:
        calls.append(req)
        return TrafficGeocodeResult(
            39.56,
            -84.10,
            req.road,
            req.exit_or_mile,
            "approved-provider",
            True,
        )

    return ApprovedTrafficGeocoder(lookup=lookup, enabled=True)


def test_end_to_end_injected_geocoding_is_still_analysis_only() -> None:
    calls: list[TrafficGeocodeRequest] = []
    result = analyze_traffic(
        _incident("Crash on I-75 NB near Exit 44"),
        _history(),
        NOW,
        region="Ohio, USA",
        geocoder=_provider(calls),
    )
    assert result.relevance == Relevance.POSSIBLY_AHEAD
    assert result.verified_geocode_source == "approved-provider"
    assert not result.driver_alert_permitted
    assert len(calls) == 1
    assert calls[0].road == "I-75"


@pytest.mark.parametrize(
    "message",
    [
        "Crash near an unknown town",
        "I-75 NB Exit 44",
        "Crash I-75 NB or SB Exit 44",
        "Crash I-75 and I-71 Exit 44",
    ],
)
def test_invalid_report_never_calls_provider(message: str) -> None:
    calls: list[TrafficGeocodeRequest] = []
    result = analyze_traffic(
        _incident(message),
        _history(),
        NOW,
        region="Ohio, USA",
        geocoder=_provider(calls),
    )
    assert result.relevance == Relevance.INSUFFICIENT
    assert not calls


def test_bad_gps_or_stale_traffic_never_calls_provider() -> None:
    calls: list[TrafficGeocodeRequest] = []
    for incident, history in (
        (_incident("Crash I-75 NB Exit 44"), _history(accuracy=100)),
        (
            _incident(
                "Crash I-75 NB Exit 44",
                timestamp=NOW - timedelta(minutes=12),
            ),
            _history(),
        ),
    ):
        result = analyze_traffic(
            incident,
            history,
            NOW,
            region="Ohio, USA",
            geocoder=_provider(calls),
        )
        assert result.relevance == Relevance.INSUFFICIENT
    assert not calls


def test_provider_disabled_by_default_means_unknown_location() -> None:
    calls: list[TrafficGeocodeRequest] = []
    provider = ApprovedTrafficGeocoder(lookup=lambda req: calls.append(req))
    result = analyze_traffic(
        _incident("Crash I-75 NB Exit 44"),
        _history(),
        NOW,
        region="Ohio, USA",
        geocoder=provider,
    )
    assert result.relevance == Relevance.INSUFFICIENT
    assert calls == []
