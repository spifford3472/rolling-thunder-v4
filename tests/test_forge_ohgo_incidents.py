"""OHGO parsing and provider tests; no network or credentials required."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from rolling_thunder.forge_ohgo_incidents import (
    ForgeOhgoIncidentProvider,
    OhgoProtocolError,
    OhgoResponse,
    OhgoState,
    parse_ohgo_incidents,
)

NOW = datetime(2026, 11, 11, 22, tzinfo=UTC)
DATA = {
    "RejectedFilters": [],
    "TotalPageCount": 1,
    "CurrentResultCount": 1,
    "TotalResultCount": 1,
    "Results": [
        {
            "Id": "ohgo-42",
            "Latitude": 39.58,
            "Longitude": -84.13,
            "RouteName": "I-75",
            "Direction": "Northbound",
            "Description": "Accident reported",
            "Location": "Near Exit 44",
            "Category": "Crash",
            "RoadStatus": "Open",
        }
    ],
}


def test_official_incident_fields_are_bounded_and_attributed() -> None:
    parsed = parse_ohgo_incidents(json.dumps(DATA).encode(), received_at=NOW)
    assert parsed.eligible_for_display
    assert parsed.source == "Ohio DOT OHGO"
    assert parsed.incidents[0].route == "I-75"
    assert parsed.incidents[0].point.latitude == 39.58


def test_without_key_never_calls_provider() -> None:
    attempts = [0]

    def fake(_url: str, _headers: dict[str, str], _timeout: float) -> OhgoResponse:
        attempts[0] += 1
        return OhgoResponse(200, json.dumps(DATA).encode(), {})

    provider = ForgeOhgoIncidentProvider(
        transport=fake,
        enabled=True,
        api_key=None,
    )
    assert provider.refresh(NOW).state == OhgoState.DISABLED
    assert attempts[0] == 0


def test_header_secret_not_in_status_and_rate_limit() -> None:
    calls: list[tuple[str, dict[str, str], float]] = []
    ticks = [100.0]

    def fake(url: str, headers: dict[str, str], timeout: float) -> OhgoResponse:
        calls.append((url, dict(headers), timeout))
        return OhgoResponse(
            200,
            json.dumps(DATA).encode(),
            {"etag": '"rev1"'},
        )

    provider = ForgeOhgoIncidentProvider(
        transport=fake,
        enabled=True,
        api_key="example-secret",
        clock=lambda: ticks[0],
    )
    assert provider.refresh(NOW).state == OhgoState.CURRENT
    assert len(calls) == 1
    assert calls[0][1]["Authorization"] == "APIKEY example-secret"
    assert "example-secret" not in repr(provider.snapshot)
    ticks[0] += 5
    assert provider.refresh(NOW).state == OhgoState.CURRENT
    assert len(calls) == 1
    ticks[0] += 121
    assert provider.refresh(NOW).state == OhgoState.CURRENT
    assert len(calls) == 2


@pytest.mark.parametrize(
    "changed",
    [
        {"RejectedFilters": [{"name": "region"}]},
        {"TotalPageCount": 2},
        {"Results": "unexpected"},
    ],
)
def test_bad_or_partial_official_response_rejected(changed: dict[str, object]) -> None:
    payload = dict(DATA)
    payload.update(changed)
    with pytest.raises(OhgoProtocolError):
        parse_ohgo_incidents(json.dumps(payload).encode(), received_at=NOW)


def test_missing_or_malformed_coordinates_are_skipped() -> None:
    payload = dict(DATA)
    payload["Results"] = [
        {"Id": "bad", "Latitude": "39.5", "Longitude": -84},
        {"Id": "ok", "Latitude": 39.5, "Longitude": -84},
        {"Id": "ok", "Latitude": 39.5, "Longitude": -84},
    ]
    payload["CurrentResultCount"] = 3
    payload["TotalResultCount"] = 3
    result = parse_ohgo_incidents(json.dumps(payload).encode(), received_at=NOW)
    assert len(result.incidents) == 1


def test_stale_and_upstream_failure_distinguished() -> None:
    ticks = [100.0]

    def fake(_url: str, _headers: dict[str, str], _timeout: float) -> OhgoResponse:
        return OhgoResponse(200, json.dumps(DATA).encode(), {})

    provider = ForgeOhgoIncidentProvider(
        transport=fake,
        api_key="fake",
        enabled=True,
        clock=lambda: ticks[0],
        minimum_interval_s=400,
    )
    assert provider.refresh(NOW).state == OhgoState.CURRENT
    ticks[0] = 200
    assert provider.refresh(NOW + timedelta(minutes=10)).state == OhgoState.STALE


def test_real_camel_case_ohgo_envelope_and_incident_fields() -> None:
    """Regression for HTTP 200 with actual OHGO JSON serialization."""

    payload = {
        "accecptedFilters": [],
        "rejectedFilters": [],
        "results": [
            {
                "id": "ohgo-42",
                "latitude": 39.58,
                "longitude": -84.13,
                "routeName": "I-75",
                "direction": "Northbound",
                "description": "Crash reported",
                "location": "Near Exit 44",
                "category": "Crash",
                "roadStatus": "Open",
            }
        ],
        "totalPageCount": 1,
        "currentResultCount": 1,
        "totalResultCount": 1,
        "lastUpdated": "2026-11-11T22:00:00Z",
        "links": [],
    }
    parsed = parse_ohgo_incidents(json.dumps(payload).encode(), received_at=NOW)
    assert parsed.state == OhgoState.CURRENT
    assert len(parsed.incidents) == 1
    assert parsed.incidents[0].route == "I-75"
    assert parsed.incidents[0].point.longitude == -84.13


def test_camel_case_rejected_filter_and_incomplete_pages_fail_closed() -> None:
    payload = {
        "results": [],
        "rejectedFilters": [{"name": "region"}],
        "currentResultCount": 0,
        "totalResultCount": 0,
        "totalPageCount": 1,
    }
    with pytest.raises(OhgoProtocolError):
        parse_ohgo_incidents(json.dumps(payload).encode(), received_at=NOW)
    payload["rejectedFilters"] = []
    payload["totalPageCount"] = 2
    with pytest.raises(OhgoProtocolError):
        parse_ohgo_incidents(json.dumps(payload).encode(), received_at=NOW)
    payload["totalPageCount"] = 1
    payload["totalResultCount"] = 1
    with pytest.raises(OhgoProtocolError):
        parse_ohgo_incidents(json.dumps(payload).encode(), received_at=NOW)


def test_conflicting_ohgo_case_aliases_are_not_silently_accepted() -> None:
    payload = {
        "results": [],
        "Results": [{"id": "mismatched"}],
        "rejectedFilters": [],
        "currentResultCount": 0,
        "totalResultCount": 0,
        "totalPageCount": 1,
    }
    with pytest.raises(OhgoProtocolError):
        parse_ohgo_incidents(json.dumps(payload).encode(), received_at=NOW)
