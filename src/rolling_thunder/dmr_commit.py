"""Background persistence controller for immutable staged DMR contacts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock, Thread
from typing import Protocol
from uuid import UUID

from pydantic import ValidationError

from rolling_thunder.dmr_contact import build_dmr_contact
from rolling_thunder.dmr_selection import StagedDmrQso
from rolling_thunder.domain import Contact
from rolling_thunder.storage import StorageError


class DmrContactWriter(Protocol):
    """Durably persist one completed contact before returning."""

    def add(self, contact: Contact) -> None:
        """Store one contact or raise a typed persistence error."""
        ...


@dataclass(frozen=True, slots=True)
class DmrCommitStatus:
    """Immutable observable state for one background DMR commit worker."""

    committing: bool = False
    active_stage_id: UUID | None = None
    last_error: str | None = None
    committed_stage_id: UUID | None = None
    committed_contact: Contact | None = None


def _ignore_started(_stage_id: UUID, _callsign: str) -> None:
    return None


def _ignore_succeeded(_stage_id: UUID, _contact: Contact) -> None:
    return None


def _ignore_failed(_stage_id: UUID, _message: str) -> None:
    return None


class DmrContactCommitController:
    """Build and persist one frozen DMR stage without blocking the caller thread."""

    def __init__(
        self,
        writer: DmrContactWriter,
        *,
        on_started: Callable[[UUID, str], None] | None = None,
        on_succeeded: Callable[[UUID, Contact], None] | None = None,
        on_failed: Callable[[UUID, str], None] | None = None,
    ) -> None:
        self._writer = writer
        self._on_started = on_started or _ignore_started
        self._on_succeeded = on_succeeded or _ignore_succeeded
        self._on_failed = on_failed or _ignore_failed
        self._lock = Lock()
        self._status = DmrCommitStatus()
        self._completed_stage_ids: set[UUID] = set()

    @property
    def status(self) -> DmrCommitStatus:
        """Return a consistent immutable worker snapshot."""
        with self._lock:
            return self._status

    def start_commit(self, staged_qso: StagedDmrQso) -> bool:
        """Accept one stage unless another write is active or this stage already succeeded."""
        stage_id = staged_qso.stage_id
        with self._lock:
            if self._status.committing or stage_id in self._completed_stage_ids:
                return False
            self._status = DmrCommitStatus(
                committing=True,
                active_stage_id=stage_id,
            )

        self._on_started(stage_id, staged_qso.callsign)
        Thread(
            target=self._commit_worker,
            args=(staged_qso,),
            daemon=True,
            name="rolling-thunder-dmr-commit",
        ).start()
        return True

    def _commit_worker(self, staged_qso: StagedDmrQso) -> None:
        stage_id = staged_qso.stage_id
        try:
            contact = build_dmr_contact(staged_qso)
            self._writer.add(contact)
        except (StorageError, ValidationError, ValueError) as error:
            message = str(error).strip() or error.__class__.__name__
            with self._lock:
                self._status = DmrCommitStatus(last_error=message)
            self._on_failed(stage_id, message)
            return

        with self._lock:
            self._completed_stage_ids.add(stage_id)
            self._status = DmrCommitStatus(
                committed_stage_id=stage_id,
                committed_contact=contact,
            )
        self._on_succeeded(stage_id, contact)
