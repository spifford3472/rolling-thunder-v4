"""Optional style-aware map route layered over the Forge spot API."""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlsplit

from rolling_thunder.forge_map import ForgeMapRenderer
from rolling_thunder.forge_spot_api import ForgeHttpResponse, ForgeSpotApiApplication
from rolling_thunder.map_tiles import MapTileError, MapTileKey

_MAP_TILE_PREFIX = "/api/v1/map/tiles/"


class MapAwareForgeSpotApiApplication(ForgeSpotApiApplication):
    """Add optional map tiles while delegating every non-map route unchanged."""

    def __init__(
        self,
        core: ForgeSpotApiApplication,
        renderer: ForgeMapRenderer | None,
    ) -> None:
        self._core = core
        self._renderer = renderer

    def handle(
        self,
        method: str,
        target: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
    ) -> ForgeHttpResponse:
        path = urlsplit(target).path
        if path.startswith(_MAP_TILE_PREFIX):
            return self._handle_tile(method.strip().upper(), path)
        return self._core.handle(method, target, headers=headers, body=body)

    def _handle_tile(self, method: str, path: str) -> ForgeHttpResponse:
        if method != "GET":
            return self.error_response(
                status_code=405,
                error="method_not_allowed",
                message="Only GET is supported by the Forge map tile endpoint.",
                extra_headers=(("Allow", "GET"),),
            )
        renderer = self._renderer
        if renderer is None:
            return self.error_response(
                status_code=503,
                error="map_tiles_unavailable",
                message="Forge map tiles are disabled or unavailable.",
            )
        remainder = path.removeprefix(_MAP_TILE_PREFIX)
        parts = remainder.split("/")
        if len(parts) != 4 or not parts[3].endswith(".png"):
            return self.error_response(
                status_code=404,
                error="not_found",
                message="The requested Forge map tile path does not exist.",
            )
        style = parts[0].strip().lower()
        if style not in {"day", "night"}:
            return self.error_response(
                status_code=400,
                error="invalid_map_tile",
                message="Map tile style must be day or night.",
            )
        try:
            key = MapTileKey(
                zoom=int(parts[1]),
                x=int(parts[2]),
                y=int(parts[3][:-4]),
            )
        except (ValueError, TypeError):
            return self.error_response(
                status_code=400,
                error="invalid_map_tile",
                message="Map tile z/x/y coordinates were invalid.",
            )
        try:
            png = renderer.fetch(style, key)
        except MapTileError as error:
            return self.error_response(
                status_code=503,
                error="map_tile_unavailable",
                message=str(error),
            )
        except Exception:  # noqa: BLE001 - optional route failure isolation boundary
            return self.error_response(
                status_code=503,
                error="map_tile_unavailable",
                message="Forge map rendering failed.",
            )
        return ForgeHttpResponse(
            status_code=200,
            headers=(
                ("Content-Type", "image/png"),
                ("Content-Length", str(len(png))),
                ("Cache-Control", "private, max-age=3600"),
                ("X-Rolling-Thunder-Map-Attribution", renderer.attribution),
            ),
            body=png,
        )
