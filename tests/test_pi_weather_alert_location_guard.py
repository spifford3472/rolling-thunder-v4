"""Tests for local GPS authority over retained Forge alert applicability."""

from datetime import UTC, datetime, timedelta

from rolling_thunder.domain import (
    GPSFixState,
    GPSPosition,
)
from rolling_thunder.forge_weather_alert_client import (
    ForgeRemoteWeatherAlertHealth,
)
from rolling_thunder.forge_weather_alerts import (
    WeatherAlertApplicability,
    WeatherAlertProviderStatus,
    WeatherAlertSnapshot,
    WeatherAlertSourceMetadata,
)
from rolling_thunder.gps import (
    GPSConnectionState,
    GPSState,
    GPSUTCObservation,
    GPSUTCSource,
)
from rolling_thunder.pi_forge_weather_alert_service import (
    PiForgeWeatherAlertErrorKind,
    PiForgeWeatherAlertState,
    PiForgeWeatherAlertStateKind,
)
from rolling_thunder.pi_weather_alert_location_guard import (
    PiWeatherAlertLocationGuard,
)

NOW = datetime(2026, 8, 9, 6, 35, tzinfo=UTC)
MONOTONIC_NOW = 102.0


def verified_state(
    *,
    latitude: float = 39.5245,
    longitude: float = -84.0625,
    fetched_at: datetime = NOW - timedelta(seconds=10),
) -> PiForgeWeatherAlertState:
    return PiForgeWeatherAlertState(
        kind=PiForgeWeatherAlertStateKind.LIVE,
        snapshot_revision=4,
        snapshot=WeatherAlertSnapshot(
            latitude=latitude,
            longitude=longitude,
            fetched_at=fetched_at,
            alerts=(),
            source=WeatherAlertSourceMetadata(
                provider_id="nws",
                provider_name="National Weather Service",
                attribution_text="National Weather Service alerts",
                attribution_url="https://www.weather.gov/",
            ),
        ),
        health=ForgeRemoteWeatherAlertHealth(
            status=WeatherAlertProviderStatus.HEALTHY,
            applicability=(
                WeatherAlertApplicability.VERIFIED_CURRENT
            ),
            revision=4,
        ),
        applicability=WeatherAlertApplicability.VERIFIED_CURRENT,
        last_attempt_at=NOW,
        last_success_at=NOW,
    )


def trusted_gps(
    *,
    latitude: float = 39.5245,
    longitude: float = -84.0625,
    trusted: bool = True,
    received_monotonic_s: float = 100.0,
) -> GPSState:
    return GPSState(
        connection_state=GPSConnectionState.CONNECTED,
        position=GPSPosition(
            fix_state=GPSFixState.THREE_DIMENSIONAL,
            latitude=latitude,
            longitude=longitude,
            speed_m_s=0.0,
            accuracy_m=3.0,
            updated_at=NOW,
        ),
        updated_at=NOW,
        utc=GPSUTCObservation(
            value=NOW,
            source=GPSUTCSource.RMC,
            valid=True,
            fix_valid=True,
            advancing=trusted,
            fresh=True,
            age_s=0.0,
            received_monotonic_s=received_monotonic_s,
        ),
    )


def guard_for(
    gps_state: GPSState,
) -> PiWeatherAlertLocationGuard:
    return PiWeatherAlertLocationGuard(
        lambda: gps_state,
        monotonic_clock=lambda: MONOTONIC_NOW,
    )


def test_current_trusted_matching_gps_preserves_verified_state() -> None:
    state = verified_state()

    effective = guard_for(
        trusted_gps()
    ).apply(state)

    assert effective is state
    assert effective.is_verified_current is True


def test_untrusted_gps_downgrades_alert_applicability() -> None:
    effective = guard_for(
        trusted_gps(trusted=False)
    ).apply(
        verified_state()
    )

    assert effective.kind is PiForgeWeatherAlertStateKind.RETAINED
    assert (
        effective.applicability
        is WeatherAlertApplicability.RETAINED_UNVERIFIED
    )
    assert effective.is_verified_current is False
    assert (
        effective.error_kind
        is PiForgeWeatherAlertErrorKind.LOCATION_UNVERIFIED
    )


def test_stale_local_gps_downgrades_alert_applicability() -> None:
    effective = guard_for(
        trusted_gps(
            received_monotonic_s=90.0,
        )
    ).apply(
        verified_state()
    )

    assert effective.is_verified_current is False
    assert effective.last_error == "Current GPS sample is stale."


def test_old_forge_alert_snapshot_is_not_current() -> None:
    effective = guard_for(
        trusted_gps()
    ).apply(
        verified_state(
            fetched_at=NOW - timedelta(seconds=61),
        )
    )

    assert effective.is_verified_current is False
    assert (
        effective.last_error
        == "Forge alert snapshot is too old for current applicability."
    )


def test_implausibly_distant_query_point_is_not_current() -> None:
    effective = guard_for(
        trusted_gps()
    ).apply(
        verified_state(
            latitude=40.0,
            longitude=-84.5,
        )
    )

    assert effective.is_verified_current is False
    assert (
        effective.last_error
        == (
            "Forge alert query point no longer matches "
            "the current GPS position."
        )
    )
