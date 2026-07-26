"""Tests for the pure dashboard station-health read model."""

from rolling_thunder.callsign_capture import CallsignCaptureState
from rolling_thunder.domain import RadioConnectionState, RadioState
from rolling_thunder.station_health import HealthStatus, build_station_health


def _radio(
    connection_state: RadioConnectionState,
    *,
    last_error: str | None = None,
) -> RadioState:
    return RadioState(connection_state=connection_state, last_error=last_error)


def test_all_available_subsystems_are_ready() -> None:
    snapshot = build_station_health(
        _radio(RadioConnectionState.CONNECTED),
        speech_enabled=True,
    )

    assert [item.label for item in snapshot.items] == [
        "Radio",
        "Voice",
        "Logging",
        "Storage",
    ]
    assert all(item.status is HealthStatus.READY for item in snapshot.items)
    assert snapshot.overall is HealthStatus.READY


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
