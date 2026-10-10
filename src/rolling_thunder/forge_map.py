"""Reusable bounded adapter for a local style-aware Forge map renderer."""

from __future__ import annotations

from threading import Lock
from time import monotonic, sleep
from urllib.error import URLError
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from rolling_thunder.http_home_platform import HttpTransport, UrllibHttpTransport
from rolling_thunder.map_tiles import MapTileError, MapTileKey, validate_map_tile_png


class ForgeMapRendererConfig(BaseModel):
    """Typed settings shared by embedded and standalone map serving."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    renderer_url_template: str = (
        "http://127.0.0.1:8080/styles/{style}/{z}/{x}/{y}.png"
    )
    request_timeout_s: float = Field(default=10.0, gt=0, le=120)
    minimum_request_interval_s: float = Field(default=0.05, ge=0, le=10)
    attribution: str = "© OpenStreetMap contributors · Protomaps"

    @field_validator("attribution")
    @classmethod
    def nonblank_attribution(cls, value: str) -> str:
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


class ForgeMapRenderer:
    """Rate-limited adapter over one local TileServer GL-compatible renderer."""

    def __init__(
        self,
        config: ForgeMapRendererConfig,
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
                headers={
                    "Accept": "image/png",
                    "User-Agent": "RollingThunder-ForgeMap/4.1",
                },
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
