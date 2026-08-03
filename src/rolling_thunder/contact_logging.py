"""Application service for committing one completed contact locally."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from rolling_thunder.contact_metadata import resolve_contact_metadata
from rolling_thunder.domain import Contact, RadioConnectionState, RadioState
from rolling_thunder.gps import GPSState
from rolling_thunder.pota_spots import PotaSpot


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

    def __init__(
        self,
        repository: ContactWriter,
        clock: Clock | None = None,
        *,
        qrz_fallback_available: bool = False,
    ) -> None:
        self._repository = repository
        self._clock = clock or SystemClock()
        self._qrz_fallback_available = qrz_fallback_available

    def commit(
        self,
        *,
        pending_callsign: str,
        radio_state: RadioState,
        rst_sent: str = "59",
        rst_received: str = "59",
        gps_state: GPSState | None = None,
        pota_context_active: bool = False,
        pota_spots: tuple[PotaSpot, ...] = (),
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

        started_at = self._clock.now()
        metadata = resolve_contact_metadata(
            callsign=callsign,
            frequency_hz=radio_state.frequency.hz,
            mode=radio_state.mode,
            reference_time=started_at,
            gps_state=gps_state,
            pota_context_active=pota_context_active,
            pota_spots=pota_spots,
            qrz_fallback_available=self._qrz_fallback_available,
        )
        contact = Contact(
            callsign=callsign,
            frequency_hz=radio_state.frequency.hz,
            mode=radio_state.mode,
            started_at=started_at,
            rst_sent=rst_sent,
            rst_received=rst_received,
            grid=metadata.grid,
            my_grid=metadata.my_grid,
            pota_reference=metadata.pota_reference,
            grid_source=metadata.grid_source,
            enrichment_state=metadata.enrichment_state,
            notes=metadata.notes,
        )
        self._repository.add(contact)
        return contact
