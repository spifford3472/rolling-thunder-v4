"""Tests for the typed GPS receiver boundary and deterministic mock."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone

import pytest

from rolling_thunder.domain import GPSFixState, GPSPosition
from rolling_thunder.gps import (
    GPSConnectionError,
    GPSConnectionState,
    GPSReceiver,
    GPSState,
)
from rolling_thunder.mock_gps import MockGPSReceiver

_FIXED_TIME = datetime(2026, 7, 26, 10, 0, tzinfo=UTC)


def _clock() -> datetime:
    return _FIXED_TIME


def _two_dimensional_position() -> GPSPosition:
    return GPSPosition(
        fix_state=GPSFixState.TWO_DIMENSIONAL,
        latitude=39.5309,
        longitude=-84.0866,
        speed_m_s=12.5,
        heading_degrees=87.0,
        accuracy_m=4.0,
        satellites=7,
        updated_at=_FIXED_TIME,
    )


def test_mock_implements_receiver_protocol() -> None:
    assert isinstance(MockGPSReceiver(clock=_clock), GPSReceiver)


def test_initial_state_is_disconnected() -> None:
    receiver = MockGPSReceiver(clock=_clock)

    state = receiver.get_state()

    assert state.connection_state is GPSConnectionState.DISCONNECTED
    assert state.position is None
    assert state.updated_at == _FIXED_TIME


def test_connect_exposes_deterministic_three_dimensional_position() -> None:
    state = MockGPSReceiver(clock=_clock).connect()

    assert state.connection_state is GPSConnectionState.CONNECTED
    assert state.position is not None
    assert state.position.fix_state is GPSFixState.THREE_DIMENSIONAL
    assert state.position.latitude == pytest.approx(39.5309)
    assert state.position.longitude == pytest.approx(-84.0866)
    assert state.position.altitude_m == pytest.approx(262.0)
    assert state.position.speed_m_s == pytest.approx(0.0)
    assert state.position.heading_degrees == pytest.approx(0.0)
    assert state.position.satellites == 10


def test_custom_initial_position_is_preserved() -> None:
    position = _two_dimensional_position()

    state = MockGPSReceiver(clock=_clock, initial_position=position).connect()

    assert state.position is position
    assert state.position.fix_state is GPSFixState.TWO_DIMENSIONAL
    assert state.position.altitude_m is None


def test_refresh_requires_connection() -> None:
    receiver = MockGPSReceiver(clock=_clock)

    with pytest.raises(GPSConnectionError, match="connected receiver"):
        receiver.refresh_state()


def test_refresh_returns_new_receiver_snapshot() -> None:
    times = iter((_FIXED_TIME, _FIXED_TIME, _FIXED_TIME + timedelta(seconds=1)))
    receiver = MockGPSReceiver(clock=lambda: next(times))
    connected = receiver.connect()

    refreshed = receiver.refresh_state()

    assert refreshed is not connected
    assert refreshed.position is connected.position
    assert refreshed.updated_at == _FIXED_TIME + timedelta(seconds=1)


def test_set_position_updates_connected_receiver() -> None:
    receiver = MockGPSReceiver(clock=_clock)
    receiver.connect()
    position = _two_dimensional_position()

    state = receiver.set_position(position)

    assert state.position is position


def test_set_position_requires_typed_position() -> None:
    receiver = MockGPSReceiver(clock=_clock)
    receiver.connect()

    with pytest.raises(TypeError, match="GPSPosition"):
        receiver.set_position("EM79xm")  # type: ignore[arg-type]


def test_simulate_no_fix_keeps_receiver_connected() -> None:
    receiver = MockGPSReceiver(clock=_clock)
    receiver.connect()

    state = receiver.simulate_no_fix()

    assert state.connection_state is GPSConnectionState.CONNECTED
    assert state.position is not None
    assert state.position.fix_state is GPSFixState.NO_FIX
    assert state.position.latitude is None
    assert state.position.longitude is None


def test_disconnect_clears_position() -> None:
    receiver = MockGPSReceiver(clock=_clock)
    receiver.connect()

    state = receiver.disconnect()

    assert state.connection_state is GPSConnectionState.DISCONNECTED
    assert state.position is None


def test_simulated_error_clears_position_and_preserves_detail() -> None:
    receiver = MockGPSReceiver(clock=_clock)
    receiver.connect()

    state = receiver.simulate_error("  serial timeout  ")

    assert state.connection_state is GPSConnectionState.ERROR
    assert state.position is None
    assert state.last_error == "serial timeout"


def test_empty_simulated_error_is_rejected() -> None:
    receiver = MockGPSReceiver(clock=_clock)

    with pytest.raises(ValueError, match="must not be empty"):
        receiver.simulate_error("  ")


def test_naive_mock_clock_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        MockGPSReceiver(clock=lambda: datetime(2026, 7, 26, 10, 0))


def test_state_timestamp_is_normalized_to_utc() -> None:
    eastern = timezone(timedelta(hours=-4))
    state = GPSState(
        connection_state=GPSConnectionState.DISCONNECTED,
        position=None,
        updated_at=datetime(2026, 7, 26, 6, 0, tzinfo=eastern),
    )

    assert state.updated_at == _FIXED_TIME
    assert state.updated_at.tzinfo is UTC


def test_state_is_immutable() -> None:
    state = MockGPSReceiver(clock=_clock).get_state()

    with pytest.raises(FrozenInstanceError):
        state.position = _two_dimensional_position()  # type: ignore[misc]


@pytest.mark.parametrize(
    ("state", "message"),
    [
        (
            GPSState,
            "Disconnected GPS state cannot contain a position",
        ),
    ],
)
def test_placeholder_for_state_validation_contract(
    state: type[GPSState],
    message: str,
) -> None:
    position = _two_dimensional_position()
    with pytest.raises(ValueError, match=message):
        state(
            connection_state=GPSConnectionState.DISCONNECTED,
            position=position,
            updated_at=_FIXED_TIME,
        )
