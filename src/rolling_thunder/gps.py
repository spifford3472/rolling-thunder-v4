"""Typed hardware-independent GPS receiver boundary."""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from rolling_thunder.domain import GPSPosition


class GPSConnectionState(StrEnum):
    """Connection state reported by a GPS receiver adapter."""

    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass(frozen=True)
class GPSState:
    """Immutable receiver state with optional current position."""

    connection_state: GPSConnectionState
    position: GPSPosition | None
    updated_at: datetime
    last_error: str | None = None

    def __post_init__(self) -> None:
        """Reject inconsistent receiver snapshots."""
        if self.updated_at.tzinfo is None or self.updated_at.utcoffset() is None:
            raise ValueError("GPS state timestamp must include timezone information.")
        object.__setattr__(self, "updated_at", self.updated_at.astimezone(UTC))

        if self.connection_state is GPSConnectionState.DISCONNECTED:
            if self.position is not None:
                raise ValueError("Disconnected GPS state cannot contain a position.")
            if self.last_error is not None:
                raise ValueError("Disconnected GPS state cannot contain an error.")

        if self.connection_state is GPSConnectionState.CONNECTED:
            if self.position is None:
                raise ValueError("Connected GPS state requires a position snapshot.")
            if self.last_error is not None:
                raise ValueError("Connected GPS state cannot contain an error.")

        if self.connection_state is GPSConnectionState.ERROR:
            if self.position is not None:
                raise ValueError("GPS error state cannot contain a position.")
            if self.last_error is None or not self.last_error.strip():
                raise ValueError("GPS error state requires a non-empty error message.")
            object.__setattr__(self, "last_error", self.last_error.strip())


class GPSError(Exception):
    """Base exception for GPS receiver operations."""


class GPSConnectionError(GPSError):
    """Raised when an operation requires a connected GPS receiver."""


@runtime_checkable
class GPSReceiver(Protocol):
    """Small typed boundary implemented by mock and physical GPS receivers."""

    def connect(self) -> GPSState:
        """Connect to the receiver and return its current state."""
        ...

    def disconnect(self) -> GPSState:
        """Disconnect from the receiver and clear its position snapshot."""
        ...

    def get_state(self) -> GPSState:
        """Return the latest immutable receiver-state snapshot."""
        ...

    def refresh_state(self) -> GPSState:
        """Read the current receiver state and return a new snapshot."""
        ...
