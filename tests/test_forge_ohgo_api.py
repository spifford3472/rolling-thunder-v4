"""Provider-neutral OHGO route contract and regression isolation tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from rolling_thunder.forge_ohgo_api import (
    ForgeOhgoBackgroundService,
    OhgoAwareForgeSpotApiApplication,
)
from rolling_thunder.forge_ohgo_incidents import (
    ForgeOhgoIncidentProvider,
    OhgoResponse,
)
from rolling_thunder.forge_spot_api import ForgeHttpResponse

NOW = datetime(2026, 11, 11, 22, tzinfo=UTC)


class FakeCore:
    """Record dispatch to the preexisting Forge API."""

    def handle(self, method: str, target: str, **kwargs: object) -> ForgeHttpResponse:
        return ForgeHttpResponse(200, (("Content-Type", "text/plain"),), b"unchanged")


def test_disabled_ohgo_endpoint_returns_unavailable_not_empty_success() -> None:
    app = OhgoAwareForgeSpotApiApplication(
        FakeCore(),
        ForgeOhgoBackgroundService(None),  # type: ignore[arg-type]
    )
    result = app.handle("GET", "/api/v1/ohgo/incidents")
    assert result.status_code == 200
    data = json.loads(result.body)
    assert data["status"] == "disabled"
    assert data["incidents"] == []
    assert data["driver_alert_permitted"] is False


def test_existing_forge_routes_and_method_guards_preserved() -> None:
    app = OhgoAwareForgeSpotApiApplication(
        FakeCore(),
        ForgeOhgoBackgroundService(None),  # type: ignore[arg-type]
    )
    assert app.handle("GET", "/api/v1/weather").body == b"unchanged"
    assert app.handle("POST", "/api/v1/ohgo/incidents").status_code == 405


def test_current_ohgo_incident_route_never_returns_credentials() -> None:
    source = {
        "Results": [
            {
                "Id": "42",
                "Latitude": 39.5,
                "Longitude": -84.1,
                "RouteName": "I-75",
                "Direction": "Southbound",
                "Location": "Near interchange",
                "Category": "Accident",
            }
        ],
        "TotalPageCount": 1,
        "CurrentResultCount": 1,
        "TotalResultCount": 1,
        "RejectedFilters": [],
    }

    def response(_url: str, _headers: object, _timeout: float) -> OhgoResponse:
        return OhgoResponse(200, json.dumps(source).encode(), {})

    provider = ForgeOhgoIncidentProvider(
        transport=response,
        enabled=True,
        api_key="SUPER-PRIVATE-KEY",
        clock=lambda: 100.0,
    )
    provider.refresh(NOW)
    app = OhgoAwareForgeSpotApiApplication(
        FakeCore(),
        ForgeOhgoBackgroundService(provider),  # type: ignore[arg-type]
    )
    reply = app.handle("GET", "/api/v1/ohgo/incidents")
    data = json.loads(reply.body)
    assert data["status"] == "current"
    assert data["incidents"][0]["route"] == "I-75"
    assert data["incident_confirmed"] is False
    assert b"SUPER-PRIVATE-KEY" not in reply.body
