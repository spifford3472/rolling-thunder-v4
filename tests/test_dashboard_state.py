"""Tests for pure dashboard presentation state."""

from datetime import UTC, datetime

from rolling_thunder.callsign_capture import CallsignCaptureState
from rolling_thunder.connectivity_status import ConnectivityStatus
from rolling_thunder.dashboard_state import build_dashboard_state, build_dashboard_ticker
from rolling_thunder.domain import (
    Frequency,
    GPSFixState,
    GPSPosition,
    RadioConnectionState,
    RadioMode,
    RadioState,
)
from rolling_thunder.gps import GPSConnectionState, GPSState


def timestamp() -> datetime:
    return datetime(2026, 7, 25, 7, 0, tzinfo=UTC)


def connected_radio() -> RadioState:
    return RadioState(
        connection_state=RadioConnectionState.CONNECTED,
        frequency=Frequency(hz=14_250_000),
        mode=RadioMode.USB,
        transmitting=False,
        updated_at=timestamp(),
    )


def gps_state(
    connection_state: GPSConnectionState,
    *,
    position: GPSPosition | None = None,
    last_error: str | None = None,
) -> GPSState:
    return GPSState(
        connection_state=connection_state,
        position=position,
        updated_at=timestamp(),
        last_error=last_error,
    )


def valid_gps_state() -> GPSState:
    return gps_state(
        GPSConnectionState.CONNECTED,
        position=GPSPosition(
            fix_state=GPSFixState.THREE_DIMENSIONAL,
            latitude=39.5309,
            longitude=-84.0866,
            altitude_m=262.0,
            satellites=10,
            updated_at=timestamp(),
        ),
    )


def test_connected_radio_formats_logger_fields() -> None:
    view = build_dashboard_state(connected_radio())

    assert view.radio_state == "CONNECTED"
    assert view.frequency == "14.250 MHz"
    assert view.band == "20 m"
    assert view.mode == "USB"
    assert view.voice_state == "READY"
    assert view.gps_state == "DISABLED"
    assert view.grid == "—"
    assert view.commit_state == "DISABLED"
    assert view.ticker == "RADIO CONNECTED — VOICE READY"
    assert "MOCK VOICE" not in view.ticker


def test_connected_radio_uses_immutable_voice_state_in_ticker() -> None:
    capture = CallsignCaptureState(voice_state="LISTENING")

    view = build_dashboard_state(connected_radio(), capture)

    assert view.ticker == "RADIO CONNECTED — VOICE LISTENING"


def test_callsign_capture_populates_logger_state() -> None:
    capture = CallsignCaptureState(
        pending_callsign="KI5VNB/VE6",
        voice_state="READY",
        commit_state="READY",
        last_result="HEARD KI5VNB/VE6",
    )

    view = build_dashboard_state(connected_radio(), capture)

    assert view.pending_callsign == "KI5VNB/VE6"
    assert view.voice_state == "READY"
    assert view.commit_state == "READY"
    assert view.last_result == "HEARD KI5VNB/VE6"


def test_disconnected_radio_uses_safe_placeholders() -> None:
    state = RadioState(
        connection_state=RadioConnectionState.DISCONNECTED,
        updated_at=timestamp(),
    )

    view = build_dashboard_state(state)

    assert view.frequency == "---.--- MHz"
    assert view.band == "--"
    assert view.mode == "--"
    assert view.ticker == "RADIO DISCONNECTED — LOGGING DISABLED"


def test_error_state_surfaces_actionable_message() -> None:
    state = RadioState(
        connection_state=RadioConnectionState.ERROR,
        updated_at=timestamp(),
        last_error="USB serial device disappeared",
    )

    view = build_dashboard_state(state)

    assert view.radio_state == "ERROR"
    assert view.ticker == "RADIO ERROR — USB serial device disappeared"


def test_disconnected_gps_uses_clear_status_without_grid() -> None:
    view = build_dashboard_state(
        connected_radio(),
        gps_state=gps_state(GPSConnectionState.DISCONNECTED),
    )

    assert view.gps_state == "DISCONNECTED"
    assert view.grid == "—"


def test_no_fix_gps_uses_clear_status_without_grid() -> None:
    position = GPSPosition(
        fix_state=GPSFixState.NO_FIX,
        updated_at=timestamp(),
    )

    view = build_dashboard_state(
        connected_radio(),
        gps_state=gps_state(GPSConnectionState.CONNECTED, position=position),
    )

    assert view.gps_state == "NO FIX"
    assert view.grid == "—"


def test_valid_gps_fix_exposes_maidenhead_grid() -> None:
    view = build_dashboard_state(
        connected_radio(),
        gps_state=valid_gps_state(),
    )

    assert view.gps_state == "READY"
    assert view.grid == "EM79wm"


def test_routine_ticker_omits_grid_and_disabled_keepalive_field() -> None:
    view = build_dashboard_state(
        connected_radio(),
        gps_state=valid_gps_state(),
        connectivity=ConnectivityStatus(
            network="DISABLED",
            home_platform="ONLINE",
            synchronization="1 SYNCED / 0 RETRYING",
            detail="CONNECTIVITY READY",
        ),
    )

    ticker = build_dashboard_ticker(view, include_network=False)

    assert view.grid == "EM79wm"
    assert ticker == (
        "RADIO CONNECTED — VOICE READY — HOME ONLINE — "
        "SYNC 1 SYNCED / 0 RETRYING"
    )
    assert "GRID" not in ticker
    assert "NETWORK" not in ticker
    assert "NETWORK DISABLED" not in ticker


def test_routine_ticker_retains_enabled_keepalive_state_and_detail() -> None:
    view = build_dashboard_state(
        connected_radio(),
        connectivity=ConnectivityStatus(
            network="OFFLINE",
            home_platform="ONLINE",
            synchronization="0 SYNCED / 1 RETRYING",
            detail="NETWORK: request timed out",
        ),
    )

    ticker = build_dashboard_ticker(view, include_network=True)

    assert "NETWORK OFFLINE" in ticker
    assert "HOME ONLINE" in ticker
    assert "SYNC 0 SYNCED / 1 RETRYING" in ticker
    assert ticker.endswith("NETWORK: request timed out")


def test_gps_error_uses_clear_status_without_grid() -> None:
    view = build_dashboard_state(
        connected_radio(),
        gps_state=gps_state(
            GPSConnectionState.ERROR,
            last_error="Serial timeout",
        ),
    )

    assert view.gps_state == "ERROR"
    assert view.grid == "—"
