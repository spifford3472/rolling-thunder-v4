"""Background controller for durable dashboard contact commits."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock, Thread

from pydantic import ValidationError

from rolling_thunder.contact_logging import ContactCommitError, ContactLoggingService
from rolling_thunder.domain import Contact, RadioState
from rolling_thunder.storage import StorageError


@dataclass(frozen=True)
class ContactCommitStatus:
    """Observable state for one background Commit operation."""

    committing: bool = False
    last_error: str | None = None
    committed_contact: Contact | None = None


class ContactCommitController:
    """Persist one contact at a time without blocking the UI thread."""

    def __init__(
        self,
        service: ContactLoggingService,
        *,
        on_started: Callable[[str], None],
        on_succeeded: Callable[[str], None],
        on_failed: Callable[[str], None],
    ) -> None:
        self._service = service
        self._on_started = on_started
        self._on_succeeded = on_succeeded
        self._on_failed = on_failed
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

        self._on_started(callsign)
        Thread(
            target=self._commit_worker,
            args=(callsign, radio_state),
            daemon=True,
        ).start()
        return True

    def _commit_worker(self, callsign: str, radio_state: RadioState) -> None:
        try:
            contact = self._service.commit(
                pending_callsign=callsign,
                radio_state=radio_state,
            )
        except (ContactCommitError, StorageError, ValidationError) as error:
            message = str(error)
            self._on_failed(message)
            with self._lock:
                self._status = ContactCommitStatus(last_error=message)
            return

        self._on_succeeded(contact.callsign)
        with self._lock:
            self._status = ContactCommitStatus(committed_contact=contact)
