"""Optional versioned weather-alert route layered over the Forge core API."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from json import dumps
from typing import Literal
from urllib.parse import urlsplit

from rolling_thunder.domain import DomainModel
from rolling_thunder.forge_spot_api import ForgeHttpResponse, ForgeSpotApiApplication
from rolling_thunder.forge_weather_alerts import (
    ForgeWeatherAlertService,
    WeatherAlertApplicability,
    WeatherAlertProviderStatus,
    WeatherAlertSnapshot,
)

_API_SCHEMA_VERSION: Literal["1"] = "1"
_WEATHER_ALERT_PATH = "/api/v1/weather-alerts"


class ForgeApiWeatherAlertHealth(DomainModel):
    """Read-only provider and point-applicability health for retained alerts."""

    status: WeatherAlertProviderStatus
    applicability: WeatherAlertApplicability
    revision: int
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None
    startup_storage_error: str | None = None
    persistence_error: str | None = None

    @classmethod
    def from_service(
        cls,
        service: ForgeWeatherAlertService,
    ) -> ForgeApiWeatherAlertHealth:
        state = service.get_state()
        return cls(
            status=state.provider_status,
            applicability=state.applicability,
            revision=state.revision,
            last_attempt_at=state.last_attempt_at,
            last_success_at=state.last_success_at,
            last_error=state.last_error,
            startup_storage_error=state.startup_storage_error,
            persistence_error=state.persistence_error,
        )


class ForgeWeatherAlertResponse(DomainModel):
    """Version-1 retained provider-neutral point-alert response."""

    api_schema_version: Literal["1"] = _API_SCHEMA_VERSION
    revision: int
    snapshot: WeatherAlertSnapshot | None = None
    health: ForgeApiWeatherAlertHealth


class WeatherAlertAwareForgeSpotApiApplication(ForgeSpotApiApplication):
    """Add optional weather-alert route while delegating core routes unchanged."""

    def __init__(
        self,
        core: ForgeSpotApiApplication,
        weather_alerts: ForgeWeatherAlertService | None,
    ) -> None:
        self._core = core
        self._weather_alerts = weather_alerts

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
        if path == _WEATHER_ALERT_PATH:
            return self._handle_weather_alerts(normalized_method)
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

    def _handle_weather_alerts(self, method: str) -> ForgeHttpResponse:
        if method != "GET":
            return self.error_response(
                status_code=405,
                error="method_not_allowed",
                message="Only GET is supported by the Forge weather-alert endpoint.",
                extra_headers=(("Allow", "GET"),),
            )
        service = self._weather_alerts
        if service is None:
            return self.error_response(
                status_code=503,
                error="weather_alerts_unavailable",
                message="Forge weather alerts are disabled or unavailable.",
            )

        state = service.get_state()
        response = ForgeWeatherAlertResponse(
            revision=state.revision,
            snapshot=state.snapshot,
            health=ForgeApiWeatherAlertHealth.from_service(service),
        )
        return self._json_response(200, response.model_dump(mode="json"))

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
