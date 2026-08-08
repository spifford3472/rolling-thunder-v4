"""Typed hardware-independent GPS receiver boundary."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from rolling_thunder.domain import GPSPosition


class GPSConnectionState(StrEnum):
    """Connection state reported by a GPS receiver adapter."""

    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    ERROR = "error"


class GPSUTCSource(StrEnum):
    """Supported source sentence for a GPS UTC observation."""

    RMC = "rmc"


@dataclass(frozen=True)
class GPSUTCObservation:
    """Immutable trust state for receiver-provided UTC independent of OS time."""

    value: datetime | None = None
    source: GPSUTCSource | None = None
    valid: bool = False
    fix_valid: bool = False
    advancing: bool = False
    fresh: bool = False
    age_s: float | None = None
    received_monotonic_s: float | None = None

    def __post_init__(self) -> None:
        if self.value is None:
            if self.source is not None:
                raise ValueError("Unavailable GPS UTC cannot have a source.")
            if self.valid or self.fix_valid or self.advancing or self.fresh:
                raise ValueError("Unavailable GPS UTC cannot carry trust flags.")
            if self.age_s is not None:
                raise ValueError("Unavailable GPS UTC cannot have an age.")
            if self.received_monotonic_s is not None:
                raise ValueError("Unavailable GPS UTC cannot have a receipt timestamp.")
            return

        if self.value.tzinfo is None or self.value.utcoffset() is None:
            raise ValueError("GPS UTC value must include timezone information.")
        object.__setattr__(self, "value", self.value.astimezone(UTC))

        if self.source is None:
            raise ValueError("Available GPS UTC requires a source.")
        if not self.valid:
            raise ValueError("Available GPS UTC must be marked valid.")
        if self.age_s is None or self.age_s < 0:
            raise ValueError("Available GPS UTC requires a non-negative age.")
        if self.received_monotonic_s is not None and self.received_monotonic_s < 0:
            raise ValueError("GPS UTC receipt timestamp cannot be negative.")

    @property
    def trusted(self) -> bool:
        """Return whether all independent GPS UTC trust criteria are satisfied."""
        return self.valid and self.fix_valid and self.advancing and self.fresh

    @classmethod
    def unavailable(cls) -> "GPSUTCObservation":
        """Return the canonical unavailable GPS UTC observation."""
        return cls()


@dataclass(frozen=True)
class GPSState:
    """Immutable receiver state with optional current position and GPS UTC."""

    connection_state: GPSConnectionState
    position: GPSPosition | None
    updated_at: datetime
    last_error: str | None = None
    utc: GPSUTCObservation = field(default_factory=GPSUTCObservation.unavailable)

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
            if self.utc.value is not None:
                raise ValueError("Disconnected GPS state cannot contain GPS UTC.")

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
            if self.utc.value is not None:
                raise ValueError("GPS error state cannot contain GPS UTC.")
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
