"""Offline tests for the optional map route on the existing Forge listener."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import cast

import pytest
from PIL import Image
from pydantic import ValidationError

from rolling_thunder.forge_config import ForgeApplicationConfig, load_forge_config
from rolling_thunder.forge_map import ForgeMapRenderer
from rolling_thunder.forge_map_api import MapAwareForgeSpotApiApplication
from rolling_thunder.forge_map_main import ForgeMapConfig, load_forge_map_config
from rolling_thunder.forge_radar import ForgeRadarService, RadarProviderFrame
from rolling_thunder.forge_radar_api import RadarAwareForgeSpotApiApplication
from rolling_thunder.forge_spot_api import ForgeHttpResponse, ForgeSpotApiApplication
from rolling_thunder.forge_spot_main import build_forge_runtime
from rolling_thunder.http_home_platform import HttpResponse, UrllibHttpResponse
from rolling_thunder.radar_domain import (
    RadarProductToken,
    RadarSourceMetadata,
)

ROOT = Path(__file__).resolve().parents[1]
STANDALONE_MAP_EXAMPLE = ROOT / "config/forge-map.example.yaml"


def png_tile() -> bytes:
    output = BytesIO()
    Image.new("RGBA", (256, 256), (10, 20, 30, 255)).save(output, format="PNG")
    return output.getvalue()


class RecordingTransport:
    def __init__(self, body: bytes | None = None, *, status_code: int = 200) -> None:
        self.body = png_tile() if body is None else body
        self.status_code = status_code
        self.requests: list[tuple[str, str, float]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_s: float,
    ) -> HttpResponse:
        del headers, body
        self.requests.append((method, url, timeout_s))
        return UrllibHttpResponse(self.status_code, self.body)


class ExplodingTransport(RecordingTransport):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_s: float,
    ) -> HttpResponse:
        del method, url, headers, body, timeout_s
        raise RuntimeError("unexpected renderer adapter failure")


class RecordingCore:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Mapping[str, str] | None, bytes | None]] = []
        self.response = ForgeHttpResponse(
            status_code=299,
            headers=(("X-Delegated", "yes"),),
            body=b"delegated",
        )

    def handle(
        self,
        method: str,
        target: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
    ) -> ForgeHttpResponse:
        self.calls.append((method, target, headers, body))
        return self.response


def renderer_for(transport: RecordingTransport) -> ForgeMapRenderer:
    config = ForgeApplicationConfig.model_validate(
        {
            "map_tiles": {
                "enabled": True,
                "renderer_url_template": (
                    "http://127.0.0.1:8080/styles/{style}/{z}/{x}/{y}.png"
                ),
                "request_timeout_s": 3.5,
                "minimum_request_interval_s": 0,
                "attribution": "Test attribution",
            }
        }
    )
    return ForgeMapRenderer(config.map_tiles, transport=transport)


def application_for(
    transport: RecordingTransport,
) -> tuple[MapAwareForgeSpotApiApplication, RecordingCore]:
    core = RecordingCore()
    application = MapAwareForgeSpotApiApplication(
        cast(ForgeSpotApiApplication, core),
        renderer_for(transport),
    )
    return application, core


def test_old_spot_yaml_without_map_section_remains_valid_and_disabled(
    tmp_path: Path,
) -> None:
    path = tmp_path / "forge-spots.yaml"
    path.write_text("pota:\n  enabled: true\n", encoding="utf-8")

    config = load_forge_config(path)

    assert config.map_tiles.enabled is False


def test_standalone_map_defaults_to_development_port_8767(tmp_path: Path) -> None:
    assert ForgeMapConfig().bind_port == 8767

    path = tmp_path / "forge-map.yaml"
    path.write_text(
        "renderer_url_template: "
        "http://127.0.0.1:8080/styles/{style}/{z}/{x}/{y}.png\n",
        encoding="utf-8",
    )

    assert load_forge_map_config(path).bind_port == 8767


def test_standalone_map_example_uses_development_port_8767() -> None:
    assert load_forge_map_config(STANDALONE_MAP_EXAMPLE).bind_port == 8767


@pytest.mark.parametrize("missing_token", ["{style}", "{z}", "{x}", "{y}"])
def test_enabled_map_renderer_template_requires_all_tokens(missing_token: str) -> None:
    template = "http://127.0.0.1:8080/styles/{style}/{z}/{x}/{y}.png".replace(
        missing_token,
        "fixed",
    )

    with pytest.raises(ValidationError, match=missing_token.replace("{", "\\{").replace("}", "\\}")):
        ForgeApplicationConfig.model_validate(
            {"map_tiles": {"enabled": True, "renderer_url_template": template}}
        )


@pytest.mark.parametrize("style", ["day", "night"])
def test_map_route_formats_style_and_coordinates_for_local_renderer(style: str) -> None:
    transport = RecordingTransport()
    application, _core = application_for(transport)

    response = application.handle("GET", f"/api/v1/map/tiles/{style}/7/34/49.png")

    assert response.status_code == 200
    assert response.body == transport.body
    assert transport.requests == [
        (
            "GET",
            f"http://127.0.0.1:8080/styles/{style}/7/34/49.png",
            3.5,
        )
    ]
    assert dict(response.headers)["Cache-Control"] == "private, max-age=3600"
    assert dict(response.headers)["X-Rolling-Thunder-Map-Attribution"] == (
        "Test attribution"
    )


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/map/tiles/dusk/7/34/49.png",
        "/api/v1/map/tiles/day/23/34/49.png",
        "/api/v1/map/tiles/night/7/128/49.png",
        "/api/v1/map/tiles/night/7/34/-1.png",
        "/api/v1/map/tiles/night/not-a-number/34/49.png",
    ],
)
def test_invalid_style_and_coordinates_fail_closed_without_renderer_work(path: str) -> None:
    transport = RecordingTransport()
    application, _core = application_for(transport)

    response = application.handle("GET", path)

    assert response.status_code == 400
    assert len(response.body) < 1_000
    assert transport.requests == []


@pytest.mark.parametrize(
    "transport",
    [
        RecordingTransport(status_code=500),
        RecordingTransport(body=b"not a png"),
        RecordingTransport(body=b"x" * 2_000_001),
    ],
)
def test_renderer_errors_and_png_bounds_affect_only_map_request(
    transport: RecordingTransport,
) -> None:
    application, core = application_for(transport)

    failed = application.handle("GET", "/api/v1/map/tiles/day/7/34/49.png")
    delegated = application.handle("GET", "/api/v1/health")

    assert failed.status_code == 503
    assert len(failed.body) < 1_000
    assert delegated is core.response
    assert core.calls == [("GET", "/api/v1/health", None, None)]


def test_unexpected_renderer_failure_is_bounded_and_isolated() -> None:
    application, core = application_for(ExplodingTransport())

    failed = application.handle("GET", "/api/v1/map/tiles/day/7/34/49.png")
    delegated = application.handle("GET", "/api/v1/weather")

    assert failed.status_code == 503
    assert b'"message":"Forge map rendering failed."' in failed.body
    assert delegated is core.response


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/health"),
        ("GET", "/api/v1/spots"),
        ("GET", "/api/v1/weather"),
        ("PUT", "/api/v1/mobile-location"),
    ],
)
def test_non_map_routes_delegate_unchanged(method: str, path: str) -> None:
    transport = RecordingTransport()
    application, core = application_for(transport)
    headers = {"Content-Type": "application/json"}
    body = b"{}"

    response = application.handle(method, path, headers=headers, body=body)

    assert response is core.response
    assert core.calls == [(method, path, headers, body)]
    assert transport.requests == []


def test_disabled_map_route_is_unavailable_and_other_routes_delegate() -> None:
    core = RecordingCore()
    application = MapAwareForgeSpotApiApplication(
        cast(ForgeSpotApiApplication, core),
        None,
    )

    unavailable = application.handle("GET", "/api/v1/map/tiles/day/7/34/49.png")
    delegated = application.handle("GET", "/api/v1/health")

    assert unavailable.status_code == 503
    assert b'"error":"map_tiles_unavailable"' in unavailable.body
    assert delegated is core.response


def test_map_head_is_explicitly_rejected_without_renderer_work() -> None:
    transport = RecordingTransport()
    application, _core = application_for(transport)

    response = application.handle("HEAD", "/api/v1/map/tiles/day/7/34/49.png")

    assert response.status_code == 405
    assert dict(response.headers)["Allow"] == "GET"
    assert transport.requests == []


class FakeLocationSource:
    def get_state(self):
        from rolling_thunder.forge_mobile_location import (
            MobileLocationRecord,
            MobileLocationState,
        )

        now = datetime(2026, 10, 7, tzinfo=UTC)
        return MobileLocationState(
            revision=1,
            location=MobileLocationRecord(
                latitude=39.5,
                longitude=-84.0,
                fix_at=now,
                received_at=now,
            ),
        )


class FakeRadarProvider:
    def discover_latest(self, location):
        del location
        now = datetime(2026, 10, 7, tzinfo=UTC)
        return RadarProviderFrame(
            provider_frame_id="frame-1",
            observed_at=now,
            source=RadarSourceMetadata(
                provider_id="test",
                provider_name="Test Radar",
                product=RadarProductToken.BASE_REFLECTIVITY,
                attribution_text="Test radar",
                attribution_url="https://example.invalid/radar",
            ),
        )

    def fetch_tile(self, provider_frame_id, key):
        del provider_frame_id, key
        return png_tile()

    def fetch_coverage(self, provider_frame_id, **kwargs):
        del provider_frame_id, kwargs
        return {}


def test_radar_and_map_layers_coexist() -> None:
    now = datetime(2026, 10, 7, tzinfo=UTC)
    radar = ForgeRadarService(
        cast("object", FakeRadarProvider()),  # type: ignore[arg-type]
        cast("object", FakeLocationSource()),  # type: ignore[arg-type]
        now=lambda: now,
    )
    radar.refresh()
    core = RecordingCore()
    radar_application = RadarAwareForgeSpotApiApplication(
        cast(ForgeSpotApiApplication, core),
        radar,
    )
    transport = RecordingTransport()
    application = MapAwareForgeSpotApiApplication(
        radar_application,
        renderer_for(transport),
    )

    radar_response = application.handle("GET", "/api/v1/radar")
    map_response = application.handle("GET", "/api/v1/map/tiles/night/7/34/49.png")

    assert radar_response.status_code == 200
    assert b'"status":"healthy"' in radar_response.body
    assert map_response.status_code == 200


class FakeServer:
    server_address = ("127.0.0.1", 8766)

    def serve_forever(self) -> None:
        return None

    def shutdown(self) -> None:
        return None

    def close(self) -> None:
        return None


def test_map_composition_uses_only_existing_spot_listener(tmp_path: Path) -> None:
    config = ForgeApplicationConfig.model_validate(
        {
            "server": {"bind_host": "127.0.0.1", "bind_port": 8766},
            "storage": {"database_path": tmp_path / "forge.db"},
            "aggregation": {"refresh_on_start": False},
            "pota": {"enabled": True},
            "map_tiles": {"enabled": True, "minimum_request_interval_s": 0},
        }
    )
    calls: list[tuple[str, int, ForgeSpotApiApplication]] = []

    def server_factory(
        host: str,
        port: int,
        application: ForgeSpotApiApplication,
    ) -> FakeServer:
        calls.append((host, port, application))
        return FakeServer()

    build_forge_runtime(
        config,
        server_factory=server_factory,
        transport=RecordingTransport(),
    )

    assert len(calls) == 1
    assert calls[0][:2] == ("127.0.0.1", 8766)
    assert calls[0][2].handle(
        "GET",
        "/api/v1/map/tiles/day/7/34/49.png",
    ).status_code == 200
