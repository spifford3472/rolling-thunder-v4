"""Pure operator-facing presentation for retained Pi weather alerts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo
from enum import StrEnum

from rolling_thunder.forge_weather_alerts import (
    WeatherAlertRecord,
    WeatherAlertSeverity,
)
from rolling_thunder.pi_forge_weather_alert_service import (
    PiForgeWeatherAlertErrorKind,
    PiForgeWeatherAlertState,
    PiForgeWeatherAlertStateKind,
)

Clock = Callable[[], datetime]

_SEVERITY_PRIORITY = {
    WeatherAlertSeverity.EXTREME: 0,
    WeatherAlertSeverity.SEVERE: 1,
    WeatherAlertSeverity.MODERATE: 2,
    WeatherAlertSeverity.MINOR: 3,
    WeatherAlertSeverity.UNKNOWN: 4,
}


class WeatherAlertPanelStatus(StrEnum):
    """Operator-facing alert availability/applicability state."""

    DISABLED = "disabled"
    NO_ACTIVE = "no_active"
    ACTIVE = "active"
    RETAINED = "retained"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class WeatherAlertItemPresentation:
    """One concise active or retained alert suitable for driving display."""

    alert_id: str
    event: str
    severity: str
    expires: str
    area: str
    headline: str


@dataclass(frozen=True)
class WeatherAlertPanelPresentation:
    """Immutable alert presentation consumed only by the Tk adapter."""

    status: WeatherAlertPanelStatus
    status_line: str
    verified_current: bool
    active_count: int
    items: tuple[WeatherAlertItemPresentation, ...]
    attribution: str


class WeatherAlertPanelController:
    """Project immutable alert state without performing external work."""

    def __init__(
        self,
        *,
        clock: Clock | None = None,
        display_timezone: tzinfo | None = None,
    ) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))
        self._display_timezone = display_timezone

    def update(
        self,
        state: PiForgeWeatherAlertState,
    ) -> WeatherAlertPanelPresentation:
        """Build one truthful location-aware weather-alert presentation."""
        now = self._aware_now()

        if state.kind is PiForgeWeatherAlertStateKind.DISABLED:
            return WeatherAlertPanelPresentation(
                status=WeatherAlertPanelStatus.DISABLED,
                status_line="WEATHER ALERTS DISABLED",
                verified_current=False,
                active_count=0,
                items=(),
                attribution="",
            )

        snapshot = state.snapshot

        if snapshot is None:
            return WeatherAlertPanelPresentation(
                status=WeatherAlertPanelStatus.UNAVAILABLE,
                status_line="WEATHER ALERTS UNAVAILABLE",
                verified_current=False,
                active_count=0,
                items=(),
                attribution="",
            )

        active = sorted(
            (
                alert
                for alert in snapshot.alerts
                if self._is_active(alert, now)
            ),
            key=self._sort_key,
        )

        items = tuple(
            self._present_alert(alert, now)
            for alert in active[:2]
        )

        attribution = snapshot.source.attribution_text

        if state.is_verified_current:
            if not active:
                return WeatherAlertPanelPresentation(
                    status=WeatherAlertPanelStatus.NO_ACTIVE,
                    status_line="NO ACTIVE WEATHER ALERTS",
                    verified_current=True,
                    active_count=0,
                    items=(),
                    attribution=attribution,
                )

            noun = "ALERT" if len(active) == 1 else "ALERTS"

            return WeatherAlertPanelPresentation(
                status=WeatherAlertPanelStatus.ACTIVE,
                status_line=(
                    f"{len(active)} ACTIVE WEATHER {noun} "
                    "• VERIFIED CURRENT"
                ),
                verified_current=True,
                active_count=len(active),
                items=items,
                attribution=attribution,
            )

        if (
            state.error_kind
            is PiForgeWeatherAlertErrorKind.LOCATION_UNVERIFIED
        ):
            status_line = "RETAINED • LOCATION NOT VERIFIED"
        else:
            status_line = "RETAINED • APPLICABILITY NOT VERIFIED"

        return WeatherAlertPanelPresentation(
            status=WeatherAlertPanelStatus.RETAINED,
            status_line=status_line,
            verified_current=False,
            active_count=len(active),
            items=items,
            attribution=attribution,
        )

    def _present_alert(
        self,
        alert: WeatherAlertRecord,
        now: datetime,
    ) -> WeatherAlertItemPresentation:
        return WeatherAlertItemPresentation(
            alert_id=alert.alert_id,
            event=alert.event,
            severity=alert.severity.value.upper(),
            expires=self._format_local_time(
                alert.expires_at,
                self._timezone_for(now),
            ),
            area=alert.area_description or "Affected area unavailable",
            headline=alert.headline,
        )

    @staticmethod
    def _is_active(
        alert: WeatherAlertRecord,
        now: datetime,
    ) -> bool:
        if alert.effective_at > now:
            return False

        if alert.expires_at <= now:
            return False

        return alert.ends_at is None or alert.ends_at > now

    @staticmethod
    def _sort_key(
        alert: WeatherAlertRecord,
    ) -> tuple[int, datetime, str]:
        return (
            _SEVERITY_PRIORITY[alert.severity],
            alert.expires_at,
            alert.event,
        )

    @staticmethod
    def _format_local_time(
        value: datetime,
        display_timezone: tzinfo,
    ) -> str:
        return (
            value.astimezone(display_timezone)
            .strftime("%I:%M %p")
            .lstrip("0")
        )

    def _timezone_for(
        self,
        now: datetime,
    ) -> tzinfo:
        if self._display_timezone is not None:
            return self._display_timezone

        local_timezone = now.astimezone().tzinfo

        if local_timezone is None:
            return UTC

        return local_timezone

    def _aware_now(self) -> datetime:
        now = self._clock()

        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError(
                "Weather-alert panel clock must return "
                "a timezone-aware datetime."
            )

        return now.astimezone(UTC)
