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
