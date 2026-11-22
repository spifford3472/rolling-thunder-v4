"""Offline coverage for the statewide Forge feed and mobile overlay lifecycle."""

from __future__ import annotations

import json
from collections.abc import Callable
from concurrent.futures import Executor, Future
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import ParamSpec, TypeVar
from urllib.parse import parse_qs, urlsplit

import pytest

from rolling_thunder.forge_ohgo_api import (
    ForgeOhgoBackgroundService,
    OhgoAwareForgeSpotApiApplication,
)
from rolling_thunder.forge_ohgo_incidents import OhgoResponse
from rolling_thunder.forge_ohgo_layers import ForgeOhgoMapLayers, parse_ohgo_layer
from rolling_thunder.live_map import GeoPoint, LiveMapGpsStatus, LiveMapPresentation
from rolling_thunder.map_tiles import build_map_viewport
from rolling_thunder.ohgo_layers import (
    OHGO_LAYERS_PATH,
    OhgoLayer,
    OhgoLayerSnapshot,
    OhgoLayerStatus,
    OhgoMarker,
    decode_ohgo_layers,
    encode_ohgo_layers,
)
from rolling_thunder.ohgo_map import OhgoMapOverlay, ohio_state_resolver
from rolling_thunder.ohgo_map_ui import draw_ohgo_marker, visible_ohgo_markers
from rolling_thunder.operator_preferences import OperatorPreferenceRepository
from rolling_thunder.settings_panel import DashboardSettingsController
from rolling_thunder.settings_selection import SettingId

NOW = datetime.now(UTC)
CLEVELAND = GeoPoint(41.5, -81.69)
LOUISVILLE = GeoPoint(38.25, -85.76)
P = ParamSpec("P")
T = TypeVar("T")


class InlineExecutor(Executor):
    def __init__(self, **_: object) -> None:
        pass

    def submit(self, fn: Callable[P, T], /, *args: P.args, **kwargs: P.kwargs) -> Future[T]:
        result: Future[T] = Future()
        try:
            result.set_result(fn(*args, **kwargs))
        except (OSError, ValueError) as error:
            result.set_exception(error)
        return result

    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:
        pass


def provider_payload(*rows: object, pages: int = 1) -> bytes:
    return json.dumps(
        {
            "rejectedFilters": [],
            "totalPageCount": pages,
            "totalResultCount": len(rows),
            "currentResultCount": len(rows),
            "results": rows,
        }
    ).encode()


@pytest.mark.parametrize(
    ("layer", "fields"),
    [
        (OhgoLayer.CONSTRUCTION, {
            "StartDate": "2026-11-01",
            "WorkZones": [{"startLocation": [-83.0, 40.0]}],
        }),
        (OhgoLayer.INCIDENTS, {"category": "Accident", "roadStatus": "Open"}),
        (OhgoLayer.DANGEROUS_SLOWDOWNS, {"normalMPH": 65, "currentMPH": 20}),
        (OhgoLayer.TRAVEL_DELAYS, {"delayTime": 11.5, "travelTime": 20.0}),
    ],
)
def test_four_provider_marker_formats(layer: OhgoLayer, fields: dict[str, object]) -> None:
    current = {"Id": "northeast", "Latitude": 41.5, "Longitude": -81.69, **fields}
    data = provider_payload(
        {"id": "bad", "latitude": True, "longitude": -82},
        {"id": "bad", "latitude": 800, "longitude": -82},
        {"id": "bad", "latitude": float("inf"), "longitude": -82},
        {"id": "bad", "latitude": 0, "longitude": 0},
        current,
        {**current, "Latitude": 40},
    )
    result = parse_ohgo_layer(data, layer, NOW)
    assert result.status is OhgoLayerStatus.CURRENT
    assert result.markers == (OhgoMarker("northeast", CLEVELAND),)


def test_private_forge_route_category_isolation_etag_and_legacy_api() -> None:
    calls = []
    remaining = iter([200, 304, 503])

    def transport(url: str, headers: dict[str, str], timeout: float) -> OhgoResponse:
        calls.append(url)
        assert headers["Authorization"] == "APIKEY fixture-key"
        assert timeout == 4
        layer = OhgoLayer(urlsplit(url).path.split("/")[-1])
        query = parse_qs(urlsplit(url).query)
        assert query["page-all"] == ["true"]
        assert "region" not in query
        if layer is OhgoLayer.CONSTRUCTION:
            assert query["exclude-work-zone"] == ["true"]
            return OhgoResponse(200, provider_payload(pages=2), {})
        if layer is OhgoLayer.INCIDENTS:
            return OhgoResponse(200, provider_payload(), {})
        if layer is OhgoLayer.TRAVEL_DELAYS:
            return OhgoResponse(503, b"", {})
        status = next(remaining)
        if status != 200:
            assert headers["If-None-Match"] == '"sample"'
        return OhgoResponse(
            status,
            provider_payload({"id": "slow", "latitude": 41.5, "longitude": -81.69}),
            {"etag": '"sample"'},
        )

    forge = ForgeOhgoMapLayers(transport, "fixture-key", clock=lambda: NOW)
    for layer in OhgoLayer:
        forge.refresh_layer(layer)
    initial = forge.snapshot
    assert forge.refresh_layer(OhgoLayer.DANGEROUS_SLOWDOWNS) == initial[1]
    app = OhgoAwareForgeSpotApiApplication(
        object(), ForgeOhgoBackgroundService(None), forge  # type: ignore[arg-type]
    )
    response = app.handle("GET", OHGO_LAYERS_PATH)
    assert response.status_code == 200
    assert b"fixture-key" not in response.body
    assert app.handle("POST", OHGO_LAYERS_PATH).status_code == 405
    assert app.handle("GET", "/api/v1/ohgo/incidents").status_code == 200
    assert decode_ohgo_layers(response.body) == initial
    assert [state.status for state in initial] == [
        OhgoLayerStatus.INCOMPLETE,
        OhgoLayerStatus.CURRENT,
        OhgoLayerStatus.CURRENT,
        OhgoLayerStatus.UNAVAILABLE,
    ]
    assert initial[2].markers == ()
    assert len(calls) == 5
    assert forge.refresh_layer(OhgoLayer.DANGEROUS_SLOWDOWNS).status is OhgoLayerStatus.UNAVAILABLE
    stale = decode_ohgo_layers(encode_ohgo_layers(initial, now=NOW + timedelta(minutes=6)))
    assert stale[1].status is OhgoLayerStatus.STALE
    assert not stale[1].markers


def test_disabled_forge_and_malformed_mobile_category() -> None:
    def unexpected_call(*_: object) -> OhgoResponse:
        pytest.fail("Disabled Forge accessed OHGO")

    disabled = ForgeOhgoMapLayers(unexpected_call, None)
    disabled.start()
    assert all(disabled.refresh_layer(layer).status == "disabled" for layer in OhgoLayer)
    wire = json.loads(encode_ohgo_layers(disabled.snapshot, now=NOW))
    wire["layers"]["incidents"] = {"status": "current", "fetched_at": NOW.isoformat(),
                                    "markers": [{"id": "x", "latitude": []}]}
    decoded = decode_ohgo_layers(json.dumps(wire).encode())
    assert decoded[2].status is OhgoLayerStatus.UNAVAILABLE
    assert decoded[0].status is OhgoLayerStatus.DISABLED


def gps(point: GeoPoint, *, current: bool = True) -> LiveMapPresentation:
    return LiveMapPresentation(LiveMapGpsStatus.READY, point, None, "", NOW, current)


def test_mobile_ohio_gate_toggles_freshness_and_offline_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("rolling_thunder.ohgo_map.ThreadPoolExecutor", InlineExecutor)
    calls = []
    now = NOW
    monotonic = 1.0
    incident = OhgoLayerSnapshot(
        OhgoLayer.INCIDENTS, OhgoLayerStatus.CURRENT, NOW, (OhgoMarker("i", CLEVELAND),)
    )
    delay = OhgoLayerSnapshot(
        OhgoLayer.TRAVEL_DELAYS, OhgoLayerStatus.CURRENT, NOW, (OhgoMarker("d", CLEVELAND),)
    )

    def fetch(url: str) -> tuple[OhgoLayerSnapshot, ...]:
        calls.append(url)
        if len(calls) > 1:
            raise OSError("Forge is offline")
        return incident, delay

    resolve = ohio_state_resolver()
    assert resolve(CLEVELAND) == "OH"
    assert resolve(LOUISVILLE) == "KY"
    overlay = OhgoMapOverlay(
        "http://forge",
        resolve,
        fetch=fetch,
        clock=lambda: now,
        monotonic=lambda: monotonic,
    )
    both = frozenset({OhgoLayer.INCIDENTS, OhgoLayer.TRAVEL_DELAYS})
    try:
        for _ in range(3):
            assert overlay.update(gps(LOUISVILLE), both) == ()
        assert overlay.update(gps(CLEVELAND), frozenset()) == ()
        assert calls == []
        assert overlay.update(gps(CLEVELAND), both) == ()
        assert overlay.update(gps(CLEVELAND), both) == ()
        assert overlay.update(gps(CLEVELAND), both) == (incident, delay)
        assert overlay.update(gps(CLEVELAND), frozenset({OhgoLayer.INCIDENTS})) == (incident,)
        assert overlay.update(gps(CLEVELAND, current=False), both) == ()
        assert overlay.update(gps(LOUISVILLE), both) == ()
        monotonic += 30
        assert overlay.update(gps(LOUISVILLE), both) == ()
        assert calls == ["http://forge"]
        assert overlay.update(gps(CLEVELAND), both) == ()
        assert overlay.update(gps(CLEVELAND), both) == (incident, delay)
        assert overlay.update(gps(CLEVELAND), both) == (incident, delay)
        assert len(calls) == 2
        now = NOW + timedelta(seconds=11)
        assert overlay.update(gps(CLEVELAND), both) == ()
        now = NOW + timedelta(minutes=6)
        fresh = LiveMapPresentation(LiveMapGpsStatus.READY, CLEVELAND, None, "", now, True)
        assert overlay.update(fresh, both) == ()
    finally:
        overlay.stop()


def test_navigation_changes_only_the_selected_layer_and_persists(tmp_path: Path) -> None:
    from rolling_thunder.operator_preferences import OperatorPreferenceService

    database = tmp_path / "rt.sqlite3"
    repo = OperatorPreferenceRepository(database)
    assert repo.read_ohgo_layers() == frozenset()
    service = OperatorPreferenceService(repo)
    controller = DashboardSettingsController(
        None, None, service, persist_ohgo_layer=service.persist_ohgo_layer,
    )
    try:
        assert controller.move_selection(6)
        assert controller.state.selection.selected is SettingId.OHGO_CONSTRUCTION
        assert controller.higher_selected()
        assert not controller.higher_selected()
        assert controller.move_selection(2)
        assert controller.higher_selected()
        assert controller.ohgo_layers == frozenset({OhgoLayer.CONSTRUCTION, OhgoLayer.INCIDENTS})
        assert controller.move_selection(-2)
        assert controller.lower_selected()
        assert service.flush(3)
        assert OperatorPreferenceRepository(database).read_ohgo_layers() == frozenset({
            OhgoLayer.INCIDENTS
        })
    finally:
        service.stop()


def test_projection_panning_zoom_density_and_marker_symbols() -> None:
    viewport = build_map_viewport(CLEVELAND, zoom=6, width_px=768, height_px=650)
    rows = tuple(
        OhgoMarker(str(i), GeoPoint(39 + (i % 100) / 40, -84.7 + i // 100 / 10))
        for i in range(4000)
    )
    layers = tuple(OhgoLayerSnapshot(layer, OhgoLayerStatus.CURRENT, NOW, rows)
                   for layer in OhgoLayer)
    visible = visible_ohgo_markers(viewport, layers)
    assert {layer for layer, _, _ in visible} == set(OhgoLayer)
    assert 0 < len(visible) <= 4 * 48
    assert all(0 <= x < 768 and 0 <= y < 650 for _, x, y in visible)
    zoomed = build_map_viewport(CLEVELAND, zoom=15, width_px=768, height_px=650)
    assert len(visible_ohgo_markers(zoomed, layers)) < len(visible)
    panned = build_map_viewport(GeoPoint(37, -122), zoom=9, width_px=768, height_px=650)
    assert visible_ohgo_markers(panned, layers) == []

    class Canvas:
        def __init__(self) -> None:
            self.items: list[dict[str, object]] = []

        def create(self, *args: object, **options: object) -> None:
            self.items.append(options)

        create_line = create_text = create_polygon = create_oval = create

    canvas = Canvas()
    for layer in OhgoLayer:
        draw_ohgo_marker(canvas, layer, 30, 30)
    assert {item.get("text") for item in canvas.items} == {None, "SLOW", "!"}
    assert {"#ff810b", "#ffe035", "#ff4747", "#2486e8"} <= {
        item["fill"] for item in canvas.items
    }
