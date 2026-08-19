"""Optional versioned radar manifest/tile routes layered over the Forge core API."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from io import BytesIO
from json import dumps
from typing import Literal
from urllib.parse import unquote, urlsplit
from zipfile import ZIP_STORED, ZipFile

from rolling_thunder.domain import DomainModel
from rolling_thunder.forge_radar import (
    ForgeRadarProviderError,
    ForgeRadarService,
    ForgeRadarState,
)
from rolling_thunder.forge_spot_api import ForgeHttpResponse, ForgeSpotApiApplication
from rolling_thunder.map_tiles import MapTileKey
from rolling_thunder.radar_domain import RadarFrame, RadarProviderStatus

_API_SCHEMA_VERSION: Literal["1"] = "1"
_RADAR_PATH = "/api/v1/radar"
_RADAR_TILE_PREFIX = "/api/v1/radar/tiles/"
_RADAR_COVERAGE_PREFIX = "/api/v1/radar/coverage/"


class ForgeApiRadarHealth(DomainModel):
    """Read-only radar provider and freshness health."""

    status: RadarProviderStatus
    stale: bool
    renderable: bool
    revision: int
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None

    @classmethod
    def from_service(cls, service: ForgeRadarService) -> "ForgeApiRadarHealth":
        state = service.get_state()
        return cls(
            status=state.provider_status,
            stale=service.is_stale(),
            renderable=service.is_renderable(),
            revision=state.revision,
            last_attempt_at=state.last_attempt_at,
            last_success_at=state.last_success_at,
            last_error=state.last_error,
        )


class ForgeRadarResponse(DomainModel):
    """Version-1 latest provider-neutral radar manifest."""

    api_schema_version: Literal["1"] = _API_SCHEMA_VERSION
    revision: int
    frame: RadarFrame | None = None
    health: ForgeApiRadarHealth


class RadarAwareForgeSpotApiApplication(ForgeSpotApiApplication):
    """Add optional radar routes while delegating every core route unchanged."""

    def __init__(
        self,
        core: ForgeSpotApiApplication,
        radar: ForgeRadarService | None,
    ) -> None:
        self._core = core
        self._radar = radar

    def handle(
        self,
        method: str,
        target: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
    ) -> ForgeHttpResponse:
        normalized_method = method.strip().upper()
        path = urlsplit(target).path
        if path == _RADAR_PATH:
            return self._handle_manifest(normalized_method)
        if path.startswith(_RADAR_COVERAGE_PREFIX):
            return self._handle_coverage(normalized_method, path)
        if path.startswith(_RADAR_TILE_PREFIX):
            return self._handle_tile(normalized_method, path)
        return self._core.handle(
            method,
            target,
            headers=headers,
            body=body,
        )

    @classmethod
    def error_response(
        cls,
        *,
        status_code: int,
        error: str,
        message: str,
        extra_headers: tuple[tuple[str, str], ...] = (),
    ) -> ForgeHttpResponse:
        return ForgeSpotApiApplication.error_response(
            status_code=status_code,
            error=error,
            message=message,
            extra_headers=extra_headers,
        )

    def _handle_manifest(self, method: str) -> ForgeHttpResponse:
        if method != "GET":
            return self.error_response(
                status_code=405,
                error="method_not_allowed",
                message="Only GET is supported by the Forge radar endpoint.",
                extra_headers=(("Allow", "GET"),),
            )
        radar = self._radar
        if radar is None:
            return self.error_response(
                status_code=503,
                error="radar_unavailable",
                message="Forge radar is disabled or unavailable.",
            )
        state: ForgeRadarState = radar.get_state()
        response = ForgeRadarResponse(
            revision=state.revision,
            frame=state.frame,
            health=ForgeApiRadarHealth.from_service(radar),
        )
        return self._json_response(200, response.model_dump(mode="json"))

    def _handle_coverage(self, method: str, path: str) -> ForgeHttpResponse:
        if method != "GET":
            return self.error_response(
                status_code=405,
                error="method_not_allowed",
                message="Only GET is supported by the Forge radar coverage endpoint.",
                extra_headers=(("Allow", "GET"),),
            )
        radar = self._radar
        if radar is None:
            return self.error_response(
                status_code=503,
                error="radar_unavailable",
                message="Forge radar is disabled or unavailable.",
            )
        remainder = path.removeprefix(_RADAR_COVERAGE_PREFIX)
        parts = remainder.split("/")
        if len(parts) != 6 or not parts[5].endswith(".zip"):
            return self.error_response(
                status_code=404,
                error="not_found",
                message="The requested Forge radar coverage path does not exist.",
            )
        frame_token = unquote(parts[0])
        try:
            zoom = int(parts[1])
            x_start = int(parts[2])
            y_start = int(parts[3])
            columns = int(parts[4])
            rows = int(parts[5][:-4])
            tiles = radar.get_coverage(
                frame_token,
                zoom=zoom,
                x_start=x_start,
                y_start=y_start,
                columns=columns,
                rows=rows,
            )
        except (ValueError, TypeError):
            return self.error_response(
                status_code=400,
                error="invalid_radar_coverage",
                message="Radar coverage coordinates or dimensions were invalid.",
            )
        except ForgeRadarProviderError as error:
            state = radar.get_state()
            status_code = 409 if state.frame is not None else 503
            return self.error_response(
                status_code=status_code,
                error="radar_coverage_unavailable",
                message=str(error),
            )

        archive_body = self._coverage_archive(tiles)
        return ForgeHttpResponse(
            status_code=200,
            headers=(
                ("Content-Type", "application/zip"),
                ("Content-Length", str(len(archive_body))),
                ("Cache-Control", "private, max-age=60"),
                ("X-Rolling-Thunder-Radar-Frame", frame_token),
                ("X-Rolling-Thunder-Radar-Tiles", str(len(tiles))),
            ),
            body=archive_body,
        )

    def _handle_tile(self, method: str, path: str) -> ForgeHttpResponse:
        if method != "GET":
            return self.error_response(
                status_code=405,
                error="method_not_allowed",
                message="Only GET is supported by the Forge radar tile endpoint.",
                extra_headers=(("Allow", "GET"),),
            )
        radar = self._radar
        if radar is None:
            return self.error_response(
                status_code=503,
                error="radar_unavailable",
                message="Forge radar is disabled or unavailable.",
            )
        remainder = path.removeprefix(_RADAR_TILE_PREFIX)
        parts = remainder.split("/")
        if len(parts) != 4 or not parts[3].endswith(".png"):
            return self.error_response(
                status_code=404,
                error="not_found",
                message="The requested Forge radar tile path does not exist.",
            )
        frame_token = unquote(parts[0])
        try:
            zoom = int(parts[1])
            x = int(parts[2])
            y = int(parts[3][:-4])
            key = MapTileKey(zoom=zoom, x=x, y=y)
        except (ValueError, TypeError):
            return self.error_response(
                status_code=400,
                error="invalid_radar_tile",
                message="Radar tile z/x/y coordinates were invalid.",
            )
        try:
            png = radar.get_tile(frame_token, key)
        except ForgeRadarProviderError as error:
            state = radar.get_state()
            status_code = 409 if state.frame is not None else 503
            return self.error_response(
                status_code=status_code,
                error="radar_tile_unavailable",
                message=str(error),
            )
        return ForgeHttpResponse(
            status_code=200,
            headers=(
                ("Content-Type", "image/png"),
                ("Content-Length", str(len(png))),
                ("Cache-Control", "private, max-age=60"),
                ("X-Rolling-Thunder-Radar-Frame", frame_token),
            ),
            body=png,
        )

    @staticmethod
    def _coverage_archive(tiles: Mapping[MapTileKey, bytes]) -> bytes:
        output = BytesIO()
        with ZipFile(output, mode="w", compression=ZIP_STORED) as archive:
            for key in sorted(tiles):
                archive.writestr(f"{key.zoom}/{key.x}/{key.y}.png", tiles[key])
        return output.getvalue()

    @staticmethod
    def _json_response(
        status_code: int,
        payload: object,
        *,
        extra_headers: tuple[tuple[str, str], ...] = (),
    ) -> ForgeHttpResponse:
        body = dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return ForgeHttpResponse(
            status_code=status_code,
            headers=(
                ("Content-Type", "application/json; charset=utf-8"),
                ("Content-Length", str(len(body))),
                ("Cache-Control", "no-store"),
                *extra_headers,
            ),
            body=body,
        )
