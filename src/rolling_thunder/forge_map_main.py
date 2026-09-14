"""Private Forge map service backed by a local styled raster renderer."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Mapping, Sequence
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from time import monotonic, sleep
from urllib.error import URLError
from urllib.parse import urlsplit

import yaml
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, ValidationError, field_validator

from rolling_thunder.http_home_platform import HttpTransport, UrllibHttpTransport
from rolling_thunder.map_tiles import MapTileError, MapTileKey, validate_map_tile_png

DEFAULT_FORGE_MAP_CONFIG_PATH = Path("config/forge-map.yaml")
_LOGGER = logging.getLogger("rolling_thunder.forge_map")


class ForgeMapConfigurationError(RuntimeError):
    """Raised when private Forge map configuration is unusable."""


class ForgeMapConfig(BaseModel):
    """Typed configuration for the isolated Forge map renderer boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    bind_host: str = "127.0.0.1"
    bind_port: int = Field(default=8766, ge=1, le=65_535)
    renderer_url_template: str = (
        "http://127.0.0.1:8080/styles/{style}/{z}/{x}/{y}.png"
    )
    request_timeout_s: float = Field(default=10.0, gt=0, le=120)
    minimum_request_interval_s: float = Field(default=0.05, ge=0, le=10)
    attribution: str = "© OpenStreetMap contributors · Protomaps"

    @field_validator("bind_host", "attribution")
    @classmethod
    def nonblank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized

    @field_validator("renderer_url_template")
    @classmethod
    def validate_renderer_url_template(cls, value: str) -> str:
        normalized = value.strip()
        parsed = urlsplit(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("must be an absolute HTTP or HTTPS URL")
        for token in ("{style}", "{z}", "{x}", "{y}"):
            if token not in normalized:
                raise ValueError(f"must contain {token}")
        return normalized


def load_forge_map_config(path: Path) -> ForgeMapConfig:
    """Load one strict YAML configuration file."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ForgeMapConfigurationError(
            f"Forge map configuration file was not found: {path}"
        ) from error
    except (OSError, yaml.YAMLError) as error:
        raise ForgeMapConfigurationError(
            f"Forge map configuration could not be read: {error}"
        ) from error
    if not isinstance(raw, dict):
        raise ForgeMapConfigurationError(
            "Forge map configuration must contain a mapping at the document root."
        )
    try:
        return ForgeMapConfig.model_validate(raw)
    except ValidationError as error:
        details = "; ".join(
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
            for item in error.errors(include_url=False)
        )
        raise ForgeMapConfigurationError(
            f"Forge map configuration validation failed: {details}"
        ) from error


class ForgeMapRenderer:
    """Rate-limited adapter over one local TileServer GL-compatible renderer."""

    def __init__(
        self,
        config: ForgeMapConfig,
        *,
        transport: HttpTransport | None = None,
    ) -> None:
        self._config = config
        self._transport = transport or UrllibHttpTransport()
        self._lock = Lock()
        self._last_request_started = 0.0

    @property
    def attribution(self) -> str:
        return self._config.attribution

    def fetch(self, style: str, key: MapTileKey) -> bytes:
        """Fetch one validated tile from the private renderer."""
        normalized_style = style.strip().lower()
        if normalized_style not in {"day", "night"}:
            raise MapTileError("Unsupported Forge map style.")
        with self._lock:
            elapsed = monotonic() - self._last_request_started
            delay = self._config.minimum_request_interval_s - elapsed
            if delay > 0:
                sleep(delay)
            self._last_request_started = monotonic()
        url = self._config.renderer_url_template.format(
            style=normalized_style,
            z=key.zoom,
            x=key.x,
            y=key.y,
        )
        try:
            response = self._transport.request(
                "GET",
                url,
                headers={"Accept": "image/png", "User-Agent": "RollingThunder-ForgeMap/4.1"},
                body=None,
                timeout_s=self._config.request_timeout_s,
            )
        except (TimeoutError, URLError, OSError) as error:
            raise MapTileError("Private Forge renderer is unavailable.") from error
        if not 200 <= response.status_code < 300:
            raise MapTileError(
                f"Private Forge renderer returned HTTP {response.status_code}."
            )
        return validate_map_tile_png(response.body)


class ForgeMapApplication:
    """Minimal versioned router for health and style-specific map tiles."""

    def __init__(self, renderer: ForgeMapRenderer) -> None:
        self._renderer = renderer

    def handle(self, method: str, target: str) -> tuple[int, tuple[tuple[str, str], ...], bytes]:
        normalized_method = method.strip().upper()
        path = urlsplit(target).path
        if path == "/api/v1/health":
            if normalized_method not in {"GET", "HEAD"}:
                return self._error(405, "Only GET and HEAD are supported.")
            body = b'{"api_schema_version":"1","service":"forge-map","status":"healthy"}'
            if normalized_method == "HEAD":
                body = b""
            return 200, (("Content-Type", "application/json"),), body
        if normalized_method != "GET":
            return self._error(405, "Only GET is supported by map tile routes.")
        prefix = "/api/v1/map/tiles/"
        if not path.startswith(prefix):
            return self._error(404, "The requested Forge map path does not exist.")
        parts = path.removeprefix(prefix).split("/")
        if len(parts) != 4 or not parts[3].endswith(".png"):
            return self._error(404, "The requested Forge map tile path does not exist.")
        style = parts[0]
        try:
            key = MapTileKey(
                zoom=int(parts[1]),
                x=int(parts[2]),
                y=int(parts[3][:-4]),
            )
            png = self._renderer.fetch(style, key)
        except (ValueError, MapTileError) as error:
            return self._error(503, str(error))
        return (
            200,
            (
                ("Content-Type", "image/png"),
                ("Cache-Control", "private, max-age=3600"),
                ("X-Rolling-Thunder-Map-Attribution", self._renderer.attribution),
            ),
            png,
        )

    @staticmethod
    def _error(status: int, message: str) -> tuple[int, tuple[tuple[str, str], ...], bytes]:
        body = message.encode("utf-8", errors="replace")[:500]
        return status, (("Content-Type", "text/plain; charset=utf-8"),), body


class _Handler(BaseHTTPRequestHandler):
    application: ForgeMapApplication

    def do_GET(self) -> None:  # noqa: N802
        self._respond("GET")

    def do_HEAD(self) -> None:  # noqa: N802
        self._respond("HEAD")

    def _respond(self, method: str) -> None:
        status, headers, body = self.application.handle(method, self.path)
        self.send_response(status)
        for name, value in headers:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if method != "HEAD":
            self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        _LOGGER.info(format, *args)


def build_server(config: ForgeMapConfig, application: ForgeMapApplication) -> ThreadingHTTPServer:
    """Build the private threaded map server."""
    handler = type("ConfiguredForgeMapHandler", (_Handler,), {"application": application})
    return ThreadingHTTPServer((config.bind_host, config.bind_port), handler)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rolling-thunder-forge-map",
        description="Private Rolling Thunder Forge map-tile service",
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_FORGE_MAP_CONFIG_PATH)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    try:
        config = load_forge_map_config(args.config)
    except ForgeMapConfigurationError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    renderer = ForgeMapRenderer(config)
    application = ForgeMapApplication(renderer)
    server = build_server(config, application)
    _LOGGER.info("Forge map API listening on http://%s:%s", config.bind_host, config.bind_port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
