"""Compatibility tests for dashboard health-table iteration."""

from datetime import UTC, datetime

from rolling_thunder.domain import (
    Frequency,
    GPSFixState,
    GPSPosition,
    RadioConnectionState,
    RadioMode,
    RadioState,
)
from rolling_thunder.gps import GPSConnectionState, GPSState
from rolling_thunder.station_health import build_station_health

_FIXED_TIME = datetime(2026, 7, 26, tzinfo=UTC)


def _radio() -> RadioState:
    return RadioState(
        connection_state=RadioConnectionState.CONNECTED,
        frequency=Frequency(hz=14_250_000),
        mode=RadioMode.USB,
        updated_at=_FIXED_TIME,
    )


def test_unconfigured_gps_is_not_added_to_legacy_health_table() -> None:
    snapshot = build_station_health(_radio(), speech_enabled=True)

    assert [item.label for item in snapshot.items] == [
        "Radio",
        "Voice",
        "Logging",
        "Storage",
    ]
    assert snapshot.gps.detail == "Not configured"


def test_configured_gps_is_added_to_health_table() -> None:
    position = GPSPosition(
        fix_state=GPSFixState.THREE_DIMENSIONAL,
        latitude=39.5309,
        longitude=-84.0866,
        altitude_m=262.0,
        updated_at=_FIXED_TIME,
    )
    gps = GPSState(
        connection_state=GPSConnectionState.CONNECTED,
        position=position,
        updated_at=_FIXED_TIME,
    )

    snapshot = build_station_health(
        _radio(),
        speech_enabled=True,
        gps_state=gps,
    )

    assert [item.label for item in snapshot.items] == [
        "Radio",
        "GPS",
        "Voice",
        "Logging",
        "Storage",
    ]
