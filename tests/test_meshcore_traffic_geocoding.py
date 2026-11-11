"""Hardware-free, offline tests for the separately gated geographic provider."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from rolling_thunder.meshcore_incident_classification import (
    PublicChannelPolicy,
    PublicMessage,
    classify_public_message,
)
from rolling_thunder.meshcore_traffic_geocoding import (
    ApprovedTrafficGeocoder,
    TrafficGeocodeRequest,
    TrafficGeocodeResult,
    request_for_reference,
)
from rolling_thunder.meshcore_traffic_georeferences import extract_traffic_georeference

NOW = datetime(2026, 11, 11, tzinfo=UTC)
REQ = TrafficGeocodeRequest("I-75", "44", "Ohio, USA")
POLICY = PublicChannelPolicy(frozenset({"traffic"}), frozenset({"other"}))


def _reference(text: str):
    incident = classify_public_message(PublicMessage("traffic", "unverified", text, NOW), POLICY)
    assert incident is not None
    return extract_traffic_georeference(incident)


def _result(**overrides: object) -> TrafficGeocodeResult:
    fields: dict[str, object] = {
        "latitude": 39.56,
        "longitude": -84.10,
        "road": "I-75",
        "exit_or_mile": "44",
        "source": "approved-map-provider",
        "point_specific": True,
    }
    fields.update(overrides)
    return TrafficGeocodeResult(**fields)  # type: ignore[arg-type]


def test_exact_request_requires_unambiguous_road_site() -> None:
    assert (
        request_for_reference(_reference("Crash I-75 northbound near exit 44"), region="Ohio, USA")
        == REQ
    )
    assert request_for_reference(_reference("Crash on I-75"), region="Ohio, USA") is None
    assert (
        request_for_reference(_reference("Crash I-75 and I-71 near Exit 44"), region="Ohio, USA")
        is None
    )


def test_provider_default_disabled_and_no_network_lookup() -> None:
    calls: list[TrafficGeocodeRequest] = []
    geocoder = ApprovedTrafficGeocoder(lookup=lambda req: calls.append(req) or _result())
    assert geocoder.resolve(REQ, now=NOW) is None
    assert calls == []


def test_cache_and_rate_limit_with_single_opted_in_provider() -> None:
    ticks = [100.0]
    calls: list[TrafficGeocodeRequest] = []

    def lookup(req: TrafficGeocodeRequest) -> TrafficGeocodeResult:
        calls.append(req)
        return _result()

    geocoder = ApprovedTrafficGeocoder(
        lookup=lookup,
        enabled=True,
        maximum_queries=1,
        clock=lambda: ticks[0],
    )
    a = geocoder.resolve(REQ, now=NOW)
    assert a is not None and a.road == "I-75"
    assert a.source == "approved-map-provider"
    assert geocoder.resolve(REQ, now=NOW + timedelta(minutes=1)) == a
    assert len(calls) == 1
    assert geocoder.resolve(TrafficGeocodeRequest("I-75", "45", "Ohio, USA"), now=NOW) is None
    assert len(calls) == 1


@pytest.mark.parametrize(
    "result",
    [
        _result(point_specific=False),
        _result(road="I-71"),
        _result(exit_or_mile="45"),
        _result(latitude=200),
        _result(source=""),
        _result(direction_verified="northbound"),
    ],
)
def test_invalid_or_generic_geocoder_result_is_not_trusted(
    result: TrafficGeocodeResult,
) -> None:
    geocoder = ApprovedTrafficGeocoder(lookup=lambda _req: result, enabled=True)
    assert geocoder.resolve(REQ, now=NOW) is None


def test_provider_failure_is_throttled_without_retry_storm() -> None:
    calls = [0]
    ticks = [100.0]

    def failing(_request: TrafficGeocodeRequest) -> TrafficGeocodeResult:
        calls[0] += 1
        raise TimeoutError("offline")

    geocoder = ApprovedTrafficGeocoder(
        lookup=failing,
        enabled=True,
        clock=lambda: ticks[0],
    )
    assert geocoder.resolve(REQ, now=NOW) is None
    assert geocoder.resolve(REQ, now=NOW) is None
    ticks[0] += 3
    # Negative result is cached instead of retrying a broken provider.
    assert geocoder.resolve(REQ, now=NOW + timedelta(seconds=3)) is None
    assert calls[0] == 1


def test_cache_expires_but_provider_budget_still_bounds_queries() -> None:
    ticks = [100.0]
    calls = [0]

    def lookup(_request: TrafficGeocodeRequest) -> TrafficGeocodeResult:
        calls[0] += 1
        return _result()

    geocoder = ApprovedTrafficGeocoder(
        lookup=lookup,
        enabled=True,
        maximum_queries=2,
        ttl=timedelta(seconds=5),
        clock=lambda: ticks[0],
    )
    assert geocoder.resolve(REQ, now=NOW) is not None
    ticks[0] += 6
    assert geocoder.resolve(REQ, now=NOW + timedelta(seconds=6)) is not None
    assert calls[0] == 2


def test_invalid_budget_and_untrusted_region_rejected() -> None:
    with pytest.raises(ValueError):
        ApprovedTrafficGeocoder(lookup=lambda _r: None, maximum_queries=101)
    with pytest.raises(ValueError):
        TrafficGeocodeRequest("I-75", "44", "")
