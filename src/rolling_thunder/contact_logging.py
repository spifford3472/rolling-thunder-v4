"""Application service for committing one completed contact locally."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from rolling_thunder.domain import Contact, RadioConnectionState, RadioState


class ContactCommitError(RuntimeError):
    """Raised when a pending contact cannot be safely committed."""


class Clock(Protocol):
    """Provide the current timestamp for deterministic contact creation."""

    def now(self) -> datetime:
        """Return the current timezone-aware time."""


class ContactWriter(Protocol):
    """Persist a completed contact before returning."""

    def add(self, contact: Contact) -> None:
        """Durably store one contact."""


class SystemClock:
    """Production UTC clock."""

    def now(self) -> datetime:
        """Return the current UTC time."""
        return datetime.now(UTC)


class ContactLoggingService:
    """Validate and transactionally persist one operator-confirmed QSO."""

    def __init__(self, repository: ContactWriter, clock: Clock | None = None) -> None:
        self._repository = repository
        self._clock = clock or SystemClock()

    def commit(
        self,
        *,
        pending_callsign: str,
        radio_state: RadioState,
        rst_sent: str = "59",
        rst_received: str = "59",
    ) -> Contact:
        """Persist one contact, returning it only after the durable write succeeds."""
        callsign = pending_callsign.strip().upper()
        if not callsign:
            raise ContactCommitError("No pending callsign is available to commit.")
        if radio_state.connection_state is not RadioConnectionState.CONNECTED:
            raise ContactCommitError("The radio must be connected before Commit.")
        if radio_state.frequency is None:
            raise ContactCommitError("The radio frequency is unavailable.")
        if radio_state.mode is None:
            raise ContactCommitError("The radio mode is unavailable.")
        if radio_state.transmitting:
            raise ContactCommitError("Commit is unavailable while the radio is transmitting.")

        contact = Contact(
            callsign=callsign,
            frequency_hz=radio_state.frequency.hz,
            mode=radio_state.mode,
            started_at=self._clock.now(),
            rst_sent=rst_sent,
            rst_received=rst_received,
        )
        self._repository.add(contact)
        return contact
