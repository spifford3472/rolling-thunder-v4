"""Tests for pure location-aware weather-alert presentation."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from rolling_thunder.forge_weather_alert_client import (
    ForgeRemoteWeatherAlertHealth,
)
from rolling_thunder.forge_weather_alerts import (
    WeatherAlertApplicability,
    WeatherAlertCertainty,
    WeatherAlertProviderStatus,
    WeatherAlertRecord,
    WeatherAlertSeverity,
    WeatherAlertSnapshot,
    WeatherAlertSourceMetadata,
    WeatherAlertUrgency,
)
from rolling_thunder.pi_forge_weather_alert_service import (
    PiForgeWeatherAlertErrorKind,
    PiForgeWeatherAlertState,
    PiForgeWeatherAlertStateKind,
)
from rolling_thunder.weather_alert_panel import (
    WeatherAlertPanelController,
    WeatherAlertPanelStatus,
)

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
EASTERN = timezone(timedelta(hours=-4))


def source() -> WeatherAlertSourceMetadata:
    return WeatherAlertSourceMetadata(
        provider_id="nws",
        provider_name="National Weather Service",
        attribution_text="National Weather Service alerts",
        attribution_url="https://www.weather.gov/",
    )


def alert(
    *,
    alert_id: str,
    event: str,
    severity: WeatherAlertSeverity,
    expires_at: datetime | None = None,
    effective_at: datetime | None = None,
    ends_at: datetime | None = None,
) -> WeatherAlertRecord:
    expiration = expires_at or NOW + timedelta(minutes=30)
    effective = effective_at or NOW - timedelta(minutes=10)

    return WeatherAlertRecord(
        alert_id=alert_id,
        event=event,
        severity=severity,
        urgency=WeatherAlertUrgency.IMMEDIATE,
        certainty=WeatherAlertCertainty.OBSERVED,
        headline=f"{event} issued for the test area",
        area_description="Warren County",
        sent_at=effective,
        effective_at=effective,
        onset_at=effective,
        ends_at=ends_at,
        expires_at=expiration,
    )


def snapshot(
    alerts: tuple[WeatherAlertRecord, ...],
) -> WeatherAlertSnapshot:
    return WeatherAlertSnapshot(
        latitude=39.5245,
        longitude=-84.0625,
        fetched_at=NOW - timedelta(seconds=10),
        alerts=alerts,
        source=source(),
    )


def live_state(
    alerts: tuple[WeatherAlertRecord, ...],
) -> PiForgeWeatherAlertState:
    return PiForgeWeatherAlertState(
        kind=PiForgeWeatherAlertStateKind.LIVE,
        snapshot_revision=3,
        snapshot=snapshot(alerts),
        health=ForgeRemoteWeatherAlertHealth(
            status=WeatherAlertProviderStatus.HEALTHY,
            applicability=(
                WeatherAlertApplicability.VERIFIED_CURRENT
            ),
            revision=3,
        ),
        applicability=WeatherAlertApplicability.VERIFIED_CURRENT,
        last_attempt_at=NOW,
        last_success_at=NOW,
    )


def retained_state(
    alerts: tuple[WeatherAlertRecord, ...],
) -> PiForgeWeatherAlertState:
    return PiForgeWeatherAlertState(
        kind=PiForgeWeatherAlertStateKind.RETAINED,
        snapshot_revision=3,
        snapshot=snapshot(alerts),
        applicability=(
            WeatherAlertApplicability.RETAINED_UNVERIFIED
        ),
        last_success_at=NOW - timedelta(seconds=20),
        error_kind=(
            PiForgeWeatherAlertErrorKind.LOCATION_UNVERIFIED
        ),
        last_error="Current GPS sample is stale.",
    )


def controller() -> WeatherAlertPanelController:
    return WeatherAlertPanelController(
        clock=lambda: NOW,
        display_timezone=EASTERN,
    )


def test_verified_empty_snapshot_shows_normal_no_active_message() -> None:
    presentation = controller().update(
        live_state(())
    )

    assert (
        presentation.status
        is WeatherAlertPanelStatus.NO_ACTIVE
    )
    assert presentation.status_line == "NO ACTIVE WEATHER ALERTS"
    assert presentation.verified_current is True
    assert presentation.active_count == 0
    assert presentation.items == ()


def test_verified_warning_shows_concise_event_severity_expiration_and_area() -> None:
    presentation = controller().update(
        live_state(
            (
                alert(
                    alert_id="tornado-1",
                    event="Tornado Warning",
                    severity=WeatherAlertSeverity.EXTREME,
                    expires_at=NOW + timedelta(minutes=30),
                ),
            )
        )
    )

    assert presentation.status is WeatherAlertPanelStatus.ACTIVE
    assert (
        presentation.status_line
        == "1 ACTIVE WEATHER ALERT • VERIFIED CURRENT"
    )
    assert presentation.verified_current is True
    assert presentation.active_count == 1

    item = presentation.items[0]

    assert item.event == "Tornado Warning"
    assert item.severity == "EXTREME"
    assert item.expires == "8:30 AM"
    assert item.area == "Warren County"
    assert item.headline == (
        "Tornado Warning issued for the test area"
    )


def test_expired_and_ended_alerts_are_not_presented_as_active() -> None:
    presentation = controller().update(
        live_state(
            (
                alert(
                    alert_id="expired",
                    event="Flash Flood Warning",
                    severity=WeatherAlertSeverity.SEVERE,
                    expires_at=NOW - timedelta(seconds=1),
                    effective_at=NOW - timedelta(hours=1),
                ),
                alert(
                    alert_id="ended",
                    event="Severe Thunderstorm Warning",
                    severity=WeatherAlertSeverity.SEVERE,
                    ends_at=NOW - timedelta(seconds=1),
                ),
            )
        )
    )

    assert (
        presentation.status
        is WeatherAlertPanelStatus.NO_ACTIVE
    )
    assert presentation.active_count == 0
    assert presentation.items == ()


def test_retained_alert_remains_visible_but_location_is_not_verified() -> None:
    presentation = controller().update(
        retained_state(
            (
                alert(
                    alert_id="watch-1",
                    event="Tornado Watch",
                    severity=WeatherAlertSeverity.SEVERE,
                ),
            )
        )
    )

    assert (
        presentation.status
        is WeatherAlertPanelStatus.RETAINED
    )
    assert (
        presentation.status_line
        == "RETAINED • LOCATION NOT VERIFIED"
    )
    assert presentation.verified_current is False
    assert presentation.active_count == 1
    assert presentation.items[0].event == "Tornado Watch"


def test_highest_severity_alerts_are_presented_first_and_display_is_bounded() -> None:
    presentation = controller().update(
        live_state(
            (
                alert(
                    alert_id="minor",
                    event="Flood Advisory",
                    severity=WeatherAlertSeverity.MINOR,
                ),
                alert(
                    alert_id="extreme",
                    event="Tornado Warning",
                    severity=WeatherAlertSeverity.EXTREME,
                ),
                alert(
                    alert_id="moderate",
                    event="Winter Weather Advisory",
                    severity=WeatherAlertSeverity.MODERATE,
                ),
            )
        )
    )

    assert presentation.active_count == 3
    assert len(presentation.items) == 2
    assert [
        item.alert_id
        for item in presentation.items
    ] == [
        "extreme",
        "moderate",
    ]


def test_disabled_and_no_data_do_not_invent_alerts() -> None:
    disabled = controller().update(
        PiForgeWeatherAlertState.disabled()
    )

    unavailable = controller().update(
        PiForgeWeatherAlertState(
            kind=PiForgeWeatherAlertStateKind.NO_DATA
        )
    )

    assert (
        disabled.status
        is WeatherAlertPanelStatus.DISABLED
    )
    assert disabled.items == ()

    assert (
        unavailable.status
        is WeatherAlertPanelStatus.UNAVAILABLE
    )
    assert unavailable.items == ()


def test_controller_rejects_naive_clock() -> None:
    alert_controller = WeatherAlertPanelController(
        clock=lambda: NOW.replace(tzinfo=None)
    )

    with pytest.raises(
        ValueError,
        match="timezone-aware",
    ):
        alert_controller.update(
            live_state(())
        )
