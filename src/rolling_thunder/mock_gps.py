"""Deterministic mock implementation of the GPS receiver boundary."""

from collections.abc import Callable
from datetime import UTC, datetime

from rolling_thunder.domain import GPSFixState, GPSPosition
from rolling_thunder.gps import GPSConnectionError, GPSConnectionState, GPSState

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    """Return the current UTC time for normal mock use."""
    return datetime.now(UTC)


class MockGPSReceiver:
    """Predictable in-memory GPS receiver for tests and mock-hardware mode."""

    def __init__(
        self,
        *,
        clock: Clock = _utc_now,
        initial_position: GPSPosition | None = None,
    ) -> None:
        self._clock = clock
        self._position = initial_position or self._default_position()
        self._connected = False
        self._state = GPSState(
            connection_state=GPSConnectionState.DISCONNECTED,
            position=None,
            updated_at=self._timestamp(),
        )

    def connect(self) -> GPSState:
        """Connect immediately and expose the configured position."""
        self._connected = True
        return self._replace_state(
            connection_state=GPSConnectionState.CONNECTED,
            position=self._position,
        )

    def disconnect(self) -> GPSState:
        """Disconnect immediately and clear the exposed position."""
        self._connected = False
        return self._replace_state(
            connection_state=GPSConnectionState.DISCONNECTED,
            position=None,
        )

    def get_state(self) -> GPSState:
        """Return the latest immutable state snapshot."""
        return self._state

    def refresh_state(self) -> GPSState:
        """Return a newly timestamped snapshot of the deterministic position."""
        self._require_connected()
        return self._replace_state(
            connection_state=GPSConnectionState.CONNECTED,
            position=self._position,
        )

    def set_position(self, position: GPSPosition) -> GPSState:
        """Replace the deterministic position while connected."""
        self._require_connected()
        if not isinstance(position, GPSPosition):
            raise TypeError("position must be a GPSPosition")
        self._position = position
        return self._replace_state(position=position)

    def simulate_no_fix(self) -> GPSState:
        """Expose a connected receiver that currently has no position fix."""
        self._require_connected()
        self._position = GPSPosition(
            fix_state=GPSFixState.NO_FIX,
            updated_at=self._timestamp(),
        )
        return self._replace_state(position=self._position)

    def simulate_error(self, message: str) -> GPSState:
        """Enter a deterministic receiver-error state."""
        normalized = message.strip()
        if not normalized:
            raise ValueError("mock GPS error message must not be empty")
        self._connected = False
        return self._replace_state(
            connection_state=GPSConnectionState.ERROR,
            position=None,
            last_error=normalized,
        )

    def _default_position(self) -> GPSPosition:
        return GPSPosition(
            fix_state=GPSFixState.THREE_DIMENSIONAL,
            latitude=39.5309,
            longitude=-84.0866,
            altitude_m=262.0,
            speed_m_s=0.0,
            heading_degrees=0.0,
            accuracy_m=3.0,
            satellites=10,
            updated_at=self._timestamp(),
        )

    def _require_connected(self) -> None:
        if not self._connected:
            raise GPSConnectionError(
                "GPS receiver operation requires a connected receiver."
            )

    def _timestamp(self) -> datetime:
        timestamp = self._clock()
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("Mock GPS clock must return a timezone-aware datetime.")
        return timestamp.astimezone(UTC)

    def _replace_state(
        self,
        *,
        connection_state: GPSConnectionState | None = None,
        position: GPSPosition | None = None,
        last_error: str | None = None,
    ) -> GPSState:
        next_connection_state = connection_state or self._state.connection_state
        next_position = position
        if next_connection_state is GPSConnectionState.CONNECTED and position is None:
            next_position = self._position

        self._state = GPSState(
            connection_state=next_connection_state,
            position=next_position,
            updated_at=self._timestamp(),
            last_error=last_error,
        )
        return self._state
