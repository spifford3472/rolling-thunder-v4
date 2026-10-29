"""Background controller for durable dashboard contact commits."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock, Thread
from typing import Protocol

from pydantic import ValidationError

from rolling_thunder.contact_logging import ContactCommitError, ContactLoggingService
from rolling_thunder.domain import Contact, ContactSource, RadioState
from rolling_thunder.gps import GPSState
from rolling_thunder.pota_spots import PotaSpot
from rolling_thunder.storage import StorageError


@dataclass(frozen=True)
class ContactCommitStatus:
    """Observable state for one background Commit operation."""

    committing: bool = False
    last_error: str | None = None
    committed_contact: Contact | None = None


class PotaWorkedRecorder(Protocol):
    """Record an already-durable POTA contact without UI-thread I/O."""

    def record_contact(
        self,
        contact: Contact,
        pota_spots: tuple[PotaSpot, ...],
    ) -> object:
        """Record the worked combination represented by the contact."""
        ...


class DxWorkedRecorder(Protocol):
    """Record an already-durable DX contact without UI-thread I/O."""

    def record_contact(self, contact: Contact) -> object:
        """Record the DX callsign-and-band combination represented by the contact."""
        ...


class ContactCommitController:
    """Persist one contact at a time without blocking the UI thread."""

    def __init__(
        self,
        service: ContactLoggingService,
        *,
        on_started: Callable[[str], None],
        on_succeeded: Callable[[str], None],
        on_failed: Callable[[str], None],
        gps_state_provider: Callable[[], GPSState | None] | None = None,
        pota_context_provider: Callable[[], bool] | None = None,
        dx_context_provider: Callable[[], bool] | None = None,
        browse_context_provider: Callable[[], bool] | None = None,
        pota_spots_provider: Callable[[], tuple[PotaSpot, ...]] | None = None,
        pota_worked_tracker: PotaWorkedRecorder | None = None,
        dx_worked_tracker: DxWorkedRecorder | None = None,
        tx_power_provider: Callable[[], int | None] | None = None,
        weather_notes_enabled: bool = False,
    ) -> None:
        self._service = service
        self._on_started = on_started
        self._on_succeeded = on_succeeded
        self._on_failed = on_failed
        self._gps_state_provider = gps_state_provider or (lambda: None)
        self._pota_context_provider = pota_context_provider or (lambda: False)
        self._dx_context_provider = dx_context_provider or (lambda: False)
        self._browse_context_provider = browse_context_provider or (lambda: False)
        self._pota_spots_provider = pota_spots_provider or (lambda: ())
        self._pota_worked_tracker = pota_worked_tracker
        self._dx_worked_tracker = dx_worked_tracker
        self._tx_power_provider = tx_power_provider or (lambda: None)
        self._weather_notes_enabled = weather_notes_enabled
        self._lock = Lock()
        self._status = ContactCommitStatus()

    @property
    def status(self) -> ContactCommitStatus:
        """Return a consistent immutable commit snapshot."""
        with self._lock:
            return self._status

    def start_commit(self, pending_callsign: str, radio_state: RadioState) -> bool:
        """Start one Commit worker, returning false when one is already active."""
        callsign = pending_callsign.strip().upper()
        with self._lock:
            if self._status.committing:
                return False
            self._status = ContactCommitStatus(committing=True)

        gps_state = self._gps_state_provider()
        pota_context_active = self._pota_context_provider()
        dx_context_active = self._dx_context_provider()
        browse_context_active = self._browse_context_provider()
        pota_spots = self._pota_spots_provider() if pota_context_active else ()

        self._on_started(callsign)
        Thread(
            target=self._commit_worker,
            args=(
                callsign,
                radio_state,
                gps_state,
                pota_context_active,
                dx_context_active,
                browse_context_active,
                pota_spots,
            ),
            daemon=True,
        ).start()
        return True

    def _commit_worker(
        self,
        callsign: str,
        radio_state: RadioState,
        gps_state: GPSState | None,
        pota_context_active: bool,
        dx_context_active: bool,
        browse_context_active: bool,
        pota_spots: tuple[PotaSpot, ...],
    ) -> None:
        try:
            tx_power_watts = self._tx_power_provider()
            contact = self._service.commit(
                pending_callsign=callsign,
                radio_state=radio_state,
                gps_state=gps_state,
                pota_context_active=pota_context_active,
                pota_spots=pota_spots,
                source=self._source_for_context(
                    pota=pota_context_active,
                    dx=dx_context_active,
                    browse=browse_context_active,
                ),
                tx_power_watts=tx_power_watts,
                weather_notes_enabled=self._weather_notes_enabled,
            )
        except (
            ContactCommitError,
            StorageError,
            ValidationError,
            ValueError,
        ) as error:
            message = str(error)
            self._on_failed(message)
            with self._lock:
                self._status = ContactCommitStatus(last_error=message)
            return

        if pota_context_active and self._pota_worked_tracker is not None:
            self._pota_worked_tracker.record_contact(contact, pota_spots)
        if dx_context_active and self._dx_worked_tracker is not None:
            self._dx_worked_tracker.record_contact(contact)

        self._on_succeeded(contact.callsign)
        with self._lock:
            self._status = ContactCommitStatus(committed_contact=contact)

    @staticmethod
    def _source_for_context(*, pota: bool, dx: bool, browse: bool) -> ContactSource:
        if pota:
            return ContactSource.POTA
        if dx:
            return ContactSource.DX
        if browse:
            return ContactSource.BROWSE
        return ContactSource.UNKNOWN
