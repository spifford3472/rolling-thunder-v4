"""Tests for the unified typed station-state read model."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from rolling_thunder.callsign_capture import CallsignCaptureState
from rolling_thunder.context_navigation import ContextId, ContextNavigationState
from rolling_thunder.domain import (
    Frequency,
    GPSFixState,
    GPSPosition,
    RadioConnectionState,
    RadioMode,
    RadioState,
)
from rolling_thunder.gps import GPSConnectionState, GPSState
from rolling_thunder.station_health import HealthStatus
from rolling_thunder.station_state import build_station_state

_FIXED_TIME = datetime(2026, 7, 26, tzinfo=UTC)


def _radio(
    connection_state: RadioConnectionState = RadioConnectionState.CONNECTED,
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
    *,
    fix_state: GPSFixState = GPSFixState.THREE_DIMENSIONAL,
) -> GPSState:
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
        connection_state=GPSConnectionState.CONNECTED,
        position=position,
        updated_at=_FIXED_TIME,
    )


def test_build_station_state_preserves_typed_inputs() -> None:
    radio = _radio()
    gps = _gps()
    capture = CallsignCaptureState(
        pending_callsign="KI5VNB",
        voice_state="READY",
        commit_state="READY",
        last_result="HEARD KI5VNB",
    )
    navigation = ContextNavigationState(selected=ContextId.DX)

    state = build_station_state(
        radio,
        capture,
        navigation,
        speech_enabled=True,
        gps_state=gps,
    )

    assert state.radio is radio
    assert state.gps is gps
    assert state.grid == "EM79wm"
    assert state.callsign_capture is capture
    assert state.context_navigation is navigation
    assert state.callsign_capture.pending_callsign == "KI5VNB"
    assert state.context_navigation.selected is ContextId.DX
    assert state.health.gps.status is HealthStatus.READY
    assert state.health.overall is HealthStatus.READY


def test_unconfigured_gps_has_no_grid_and_preserves_ready_state() -> None:
    state = build_station_state(
        _radio(),
        CallsignCaptureState(),
        ContextNavigationState(),
        speech_enabled=True,
    )

    assert state.gps is None
    assert state.grid is None
    assert state.health.gps.status is HealthStatus.DISABLED
    assert state.health.overall is HealthStatus.READY


def test_no_fix_has_no_grid_and_degrades_health() -> None:
    state = build_station_state(
        _radio(),
        CallsignCaptureState(),
        ContextNavigationState(),
        speech_enabled=True,
        gps_state=_gps(fix_state=GPSFixState.NO_FIX),
    )

    assert state.grid is None
    assert state.health.gps.status is HealthStatus.DEGRADED
    assert state.health.overall is HealthStatus.DEGRADED


def test_disconnected_gps_has_no_grid() -> None:
    gps = GPSState(
        connection_state=GPSConnectionState.DISCONNECTED,
        position=None,
        updated_at=_FIXED_TIME,
    )

    state = build_station_state(
        _radio(),
        CallsignCaptureState(),
        ContextNavigationState(),
        speech_enabled=True,
        gps_state=gps,
    )

    assert state.gps is gps
    assert state.grid is None
    assert state.health.gps.status is HealthStatus.UNAVAILABLE
    assert state.health.overall is HealthStatus.DEGRADED


def test_health_matches_disconnected_radio_state() -> None:
    state = build_station_state(
        _radio(RadioConnectionState.DISCONNECTED),
        CallsignCaptureState(pending_callsign="KI5VNB", commit_state="READY"),
        ContextNavigationState(),
        speech_enabled=True,
    )

    assert state.radio.connection_state is RadioConnectionState.DISCONNECTED
    assert state.callsign_capture.pending_callsign == "KI5VNB"
    assert state.health.radio.status is HealthStatus.UNAVAILABLE
    assert state.health.overall is HealthStatus.UNAVAILABLE


def test_disabled_voice_is_reflected_without_losing_capture_state() -> None:
    capture = CallsignCaptureState(
        pending_callsign="NC4XL",
        voice_state="READY",
        commit_state="READY",
    )

    state = build_station_state(
        _radio(),
        capture,
        ContextNavigationState(selected=ContextId.SETTINGS),
        speech_enabled=False,
    )

    assert state.callsign_capture is capture
    assert state.health.voice.status is HealthStatus.DISABLED
    assert state.health.overall is HealthStatus.DEGRADED
    assert state.context_navigation.selected is ContextId.SETTINGS


@pytest.mark.parametrize(
    ("logging_available", "storage_available", "failed_subsystem"),
    [
        (False, True, "logging"),
        (True, False, "storage"),
    ],
)
def test_required_service_failure_makes_station_unavailable(
    logging_available: bool,
    storage_available: bool,
    failed_subsystem: str,
) -> None:
    state = build_station_state(
        _radio(),
        CallsignCaptureState(),
        ContextNavigationState(),
        speech_enabled=True,
        logging_available=logging_available,
        storage_available=storage_available,
    )

    item = getattr(state.health, failed_subsystem)
    assert item.status is HealthStatus.UNAVAILABLE
    assert state.health.overall is HealthStatus.UNAVAILABLE


def test_equal_inputs_produce_equal_station_state() -> None:
    radio = _radio()
    gps = _gps()
    capture = CallsignCaptureState(pending_callsign="W8O", commit_state="READY")
    navigation = ContextNavigationState(selected=ContextId.POTA)

    first = build_station_state(
        radio,
        capture,
        navigation,
        speech_enabled=True,
        gps_state=gps,
    )
    second = build_station_state(
        radio,
        capture,
        navigation,
        speech_enabled=True,
        gps_state=gps,
    )

    assert first == second


def test_station_state_is_immutable() -> None:
    state = build_station_state(
        _radio(),
        CallsignCaptureState(),
        ContextNavigationState(),
        speech_enabled=True,
    )

    with pytest.raises(FrozenInstanceError):
        state.callsign_capture = CallsignCaptureState()  # type: ignore[misc]
