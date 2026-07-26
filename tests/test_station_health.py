"""Tests for the pure dashboard station-health read model."""

from datetime import UTC, datetime

from rolling_thunder.callsign_capture import CallsignCaptureState
from rolling_thunder.domain import (
    Frequency,
    GPSFixState,
    GPSPosition,
    RadioConnectionState,
    RadioMode,
    RadioState,
)
from rolling_thunder.gps import GPSConnectionState, GPSState
from rolling_thunder.station_health import HealthStatus, build_station_health

_FIXED_TIME = datetime(2026, 7, 26, tzinfo=UTC)


def _radio(
    connection_state: RadioConnectionState,
    *,
    last_error: str | None = None,
) -> RadioState:
    state_data: dict[str, object] = {
        "connection_state": connection_state,
        "last_error": last_error,
        "updated_at": _FIXED_TIME,
    }
    if connection_state is RadioConnectionState.CONNECTED:
        state_data.update(
            frequency=Frequency(hz=14_250_000),
            mode=RadioMode.USB,
            transmitting=False,
        )
    return RadioState.model_validate(state_data)


def _gps(
    connection_state: GPSConnectionState = GPSConnectionState.CONNECTED,
    *,
    fix_state: GPSFixState = GPSFixState.THREE_DIMENSIONAL,
    last_error: str | None = None,
) -> GPSState:
    position: GPSPosition | None = None
    if connection_state is GPSConnectionState.CONNECTED:
        if fix_state is GPSFixState.NO_FIX:
            position = GPSPosition(fix_state=fix_state, updated_at=_FIXED_TIME)
        else:
            position = GPSPosition(
                fix_state=fix_state,
                latitude=39.5309,
                longitude=-84.0866,
                altitude_m=262.0 if fix_state is GPSFixState.THREE_DIMENSIONAL else None,
                updated_at=_FIXED_TIME,
            )
    return GPSState(
        connection_state=connection_state,
        position=position,
        updated_at=_FIXED_TIME,
        last_error=last_error,
    )


def test_all_available_subsystems_are_ready() -> None:
    snapshot = build_station_health(
        _radio(RadioConnectionState.CONNECTED),
        speech_enabled=True,
        gps_state=_gps(),
    )

    assert [item.label for item in snapshot.items] == [
        "Radio",
        "GPS",
        "Voice",
        "Logging",
        "Storage",
    ]
    assert all(item.status is HealthStatus.READY for item in snapshot.items)
    assert snapshot.overall is HealthStatus.READY


def test_unconfigured_gps_is_disabled_without_degrading_station() -> None:
    snapshot = build_station_health(
        _radio(RadioConnectionState.CONNECTED),
        speech_enabled=True,
    )

    assert snapshot.gps.status is HealthStatus.DISABLED
    assert snapshot.gps.detail == "Not configured"
    assert snapshot.overall is HealthStatus.READY


def test_gps_no_fix_degrades_station_awareness() -> None:
    snapshot = build_station_health(
        _radio(RadioConnectionState.CONNECTED),
        speech_enabled=True,
        gps_state=_gps(fix_state=GPSFixState.NO_FIX),
    )

    assert snapshot.gps.status is HealthStatus.DEGRADED
    assert snapshot.gps.detail == "No fix"
    assert snapshot.overall is HealthStatus.DEGRADED


def test_disconnected_gps_degrades_without_disabling_logging() -> None:
    snapshot = build_station_health(
        _radio(RadioConnectionState.CONNECTED),
        speech_enabled=True,
        gps_state=_gps(GPSConnectionState.DISCONNECTED),
    )

    assert snapshot.gps.status is HealthStatus.UNAVAILABLE
    assert snapshot.gps.detail == "Disconnected"
    assert snapshot.logging.status is HealthStatus.READY
    assert snapshot.overall is HealthStatus.DEGRADED


def test_gps_error_detail_is_preserved() -> None:
    snapshot = build_station_health(
        _radio(RadioConnectionState.CONNECTED),
        speech_enabled=True,
        gps_state=_gps(GPSConnectionState.ERROR, last_error="Serial timeout"),
    )

    assert snapshot.gps.status is HealthStatus.UNAVAILABLE
    assert snapshot.gps.detail == "Serial timeout"
    assert snapshot.overall is HealthStatus.DEGRADED


def test_disabled_voice_degrades_but_does_not_disable_logging() -> None:
    snapshot = build_station_health(
        _radio(RadioConnectionState.CONNECTED),
        speech_enabled=False,
    )

    assert snapshot.voice.status is HealthStatus.DISABLED
    assert snapshot.voice.detail == "Disabled by configuration"
    assert snapshot.logging.status is HealthStatus.READY
    assert snapshot.overall is HealthStatus.DEGRADED


def test_voice_failure_is_degraded() -> None:
    snapshot = build_station_health(
        _radio(RadioConnectionState.CONNECTED),
        CallsignCaptureState(voice_state="FAILED"),
        speech_enabled=True,
    )

    assert snapshot.voice.status is HealthStatus.DEGRADED
    assert snapshot.overall is HealthStatus.DEGRADED


def test_active_voice_is_reported_as_listening() -> None:
    snapshot = build_station_health(
        _radio(RadioConnectionState.CONNECTED),
        CallsignCaptureState(voice_state="LISTENING"),
        speech_enabled=True,
    )

    assert snapshot.voice.status is HealthStatus.READY
    assert snapshot.voice.detail == "Listening"


def test_disconnected_radio_makes_station_unavailable() -> None:
    snapshot = build_station_health(
        _radio(RadioConnectionState.DISCONNECTED),
        speech_enabled=True,
    )

    assert snapshot.radio.status is HealthStatus.UNAVAILABLE
    assert snapshot.radio.detail == "Disconnected"
    assert snapshot.overall is HealthStatus.UNAVAILABLE


def test_radio_error_is_preserved_as_detail() -> None:
    snapshot = build_station_health(
        _radio(RadioConnectionState.ERROR, last_error="CAT timeout"),
        speech_enabled=True,
    )

    assert snapshot.radio.status is HealthStatus.UNAVAILABLE
    assert snapshot.radio.detail == "CAT timeout"


def test_logging_failure_makes_station_unavailable() -> None:
    snapshot = build_station_health(
        _radio(RadioConnectionState.CONNECTED),
        speech_enabled=True,
        logging_available=False,
    )

    assert snapshot.logging.status is HealthStatus.UNAVAILABLE
    assert snapshot.overall is HealthStatus.UNAVAILABLE


def test_storage_failure_makes_station_unavailable() -> None:
    snapshot = build_station_health(
        _radio(RadioConnectionState.CONNECTED),
        speech_enabled=True,
        storage_available=False,
    )

    assert snapshot.storage.status is HealthStatus.UNAVAILABLE
    assert snapshot.overall is HealthStatus.UNAVAILABLE
