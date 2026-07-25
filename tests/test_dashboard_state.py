"""Tests for pure dashboard presentation state."""

from datetime import UTC, datetime

from rolling_thunder.callsign_capture import CallsignCaptureState
from rolling_thunder.dashboard_state import build_dashboard_state
from rolling_thunder.domain import (
    Frequency,
    RadioConnectionState,
    RadioMode,
    RadioState,
)


def timestamp() -> datetime:
    return datetime(2026, 7, 25, 7, 0, tzinfo=UTC)


def test_connected_radio_formats_logger_fields() -> None:
    state = RadioState(
        connection_state=RadioConnectionState.CONNECTED,
        frequency=Frequency(hz=14_250_000),
        mode=RadioMode.USB,
        transmitting=False,
        updated_at=timestamp(),
    )

    view = build_dashboard_state(state)

    assert view.radio_state == "CONNECTED"
    assert view.frequency == "14.250 MHz"
    assert view.band == "20 m"
    assert view.mode == "USB"
    assert view.voice_state == "READY"
    assert view.commit_state == "DISABLED"
    assert view.ticker == "RADIO CONNECTED — MOCK VOICE READY"


def test_callsign_capture_populates_logger_state() -> None:
    state = RadioState(
        connection_state=RadioConnectionState.CONNECTED,
        frequency=Frequency(hz=14_250_000),
        mode=RadioMode.USB,
        transmitting=False,
        updated_at=timestamp(),
    )
    capture = CallsignCaptureState(
        pending_callsign="KI5VNB/VE6",
        voice_state="READY",
        commit_state="READY",
        last_result="HEARD KI5VNB/VE6",
    )

    view = build_dashboard_state(state, capture)

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
