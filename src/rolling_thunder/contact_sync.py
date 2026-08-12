"""Deterministic synchronization of locally stored contacts."""

from collections.abc import Callable
from datetime import UTC, datetime
from threading import Lock
from typing import Protocol
from uuid import UUID

from pydantic import Field

from rolling_thunder.domain import (
    Contact,
    ContactEnrichmentState,
    DomainModel,
    SynchronizationState,
)
from rolling_thunder.home_platform import (
    ContactUploadRequest,
    HomePlatformClient,
    HomePlatformError,
)
from rolling_thunder.radio_polling import PollScheduler, ScheduledPoll

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ContactSyncRepository(Protocol):
    """Persistence operations required by the synchronization service."""

    def get(self, contact_id: UUID) -> Contact | None:
        """Return one contact by UUID, or None when absent."""
        ...

    def list_synchronization_eligible(
        self,
        state: SynchronizationState,
        *,
        limit: int = 100,
    ) -> list[Contact]:
        """Return synchronization-ready contacts in one state."""
        ...

    def update_synchronization_state(
        self,
        contact_id: UUID,
        state: SynchronizationState,
    ) -> Contact:
        """Persist and return a contact's new synchronization state."""
        ...


class ContactRetryStore(Protocol):
    """Restart-safe retry metadata used by contact synchronization."""

    def list_due_contact_ids(self, due_at: datetime, *, limit: int) -> list[UUID]:
        """Return failed contact IDs whose retry time has arrived."""
        ...

    def record_failure(
        self,
        contact_id: UUID,
        *,
        failed_at: datetime,
        error_message: str,
        initial_delay_s: float,
        max_delay_s: float,
    ) -> object:
        """Persist the next exponential-backoff attempt."""
        ...

    def clear(self, contact_id: UUID) -> None:
        """Remove retry metadata after synchronization succeeds."""
        ...


class ContactSyncResult(DomainModel):
    """Immutable summary of one synchronization run."""

    attempted: int = Field(ge=0)
    synchronized: int = Field(ge=0)
    failed: int = Field(ge=0)


class ContactSyncService:
    """Upload eligible contacts without coupling network failures to local logging."""

    def __init__(
        self,
        repository: ContactSyncRepository,
        client: HomePlatformClient,
        scheduler: PollScheduler,
        *,
        interval_s: float = 30.0,
        batch_size: int = 25,
        retry_store: ContactRetryStore | None = None,
        retry_initial_delay_s: float = 5.0,
        retry_max_delay_s: float = 300.0,
        clock: Clock = _utc_now,
    ) -> None:
        if interval_s <= 0:
            raise ValueError("Contact synchronization interval must be positive.")
        if batch_size <= 0:
            raise ValueError("Contact synchronization batch size must be positive.")
        if retry_initial_delay_s <= 0 or retry_max_delay_s <= 0:
            raise ValueError("Contact synchronization retry delays must be positive.")
        if retry_max_delay_s < retry_initial_delay_s:
            raise ValueError(
                "Contact synchronization maximum retry delay must not be below the initial delay."
            )

        self._repository = repository
        self._client = client
        self._scheduler = scheduler
        self._interval_s = interval_s
        self._batch_size = batch_size
        self._retry_store = retry_store
        self._retry_initial_delay_s = retry_initial_delay_s
        self._retry_max_delay_s = retry_max_delay_s
        self._clock = clock
        self._scheduled_poll: ScheduledPoll | None = None
        self._sync_lock = Lock()
        self._latest_result = ContactSyncResult(
            attempted=0,
            synchronized=0,
            failed=0,
        )

    @property
    def is_running(self) -> bool:
        """Return whether future synchronization runs are scheduled."""
        return self._scheduled_poll is not None

    @property
    def latest_result(self) -> ContactSyncResult:
        """Return the latest immutable synchronization summary."""
        return self._latest_result

    @property
    def synchronizing(self) -> bool:
        """Return whether a periodic or manual synchronization run owns the single-flight lock."""
        acquired = self._sync_lock.acquire(blocking=False)
        if not acquired:
            return True
        self._sync_lock.release()
        return False

    def start(self) -> ContactSyncResult:
        """Schedule synchronization without performing startup network I/O."""
        if self.is_running:
            raise RuntimeError("Contact synchronization service is already running.")

        self._scheduled_poll = self._scheduler.schedule_repeating(
            self._interval_s,
            self._synchronize_once,
        )
        return self._latest_result

    def stop(self) -> ContactSyncResult:
        """Stop future synchronization runs and return the latest summary."""
        scheduled_poll = self._scheduled_poll
        self._scheduled_poll = None
        if scheduled_poll is not None:
            scheduled_poll.cancel()
        return self._latest_result

    def synchronize_now(self) -> ContactSyncResult:
        """Operator-requested sync of pending and failed contacts, ignoring retry delay."""
        return self._synchronize(force_failed=True)

    def synchronize_due_now(self) -> ContactSyncResult:
        """Opportunistic sync of pending plus retry-due failed contacts."""
        return self._synchronize(force_failed=False)

    def _synchronize(self, *, force_failed: bool) -> ContactSyncResult:
        if not self._sync_lock.acquire(blocking=False):
            return self._latest_result
        try:
            return self._run_once(force_failed=force_failed)
        finally:
            self._sync_lock.release()

    def _synchronize_once(self) -> None:
        if not self.is_running:
            return
        self.synchronize_due_now()

    def _run_once(self, *, force_failed: bool) -> ContactSyncResult:
        attempted = 0
        synchronized = 0
        failed = 0
        contacts = self._eligible_contacts(force_failed=force_failed)
        for contact in contacts:
            attempted += 1
            try:
                self._client.upload_contact(ContactUploadRequest(contact=contact))
            except HomePlatformError as error:
                self._repository.update_synchronization_state(
                    contact.contact_id,
                    SynchronizationState.FAILED,
                )
                if self._retry_store is not None:
                    self._retry_store.record_failure(
                        contact.contact_id,
                        failed_at=self._timestamp(),
                        error_message=str(error),
                        initial_delay_s=self._retry_initial_delay_s,
                        max_delay_s=self._retry_max_delay_s,
                    )
                failed += 1
                continue

            self._repository.update_synchronization_state(
                contact.contact_id,
                SynchronizationState.SYNCHRONIZED,
            )
            if self._retry_store is not None:
                self._retry_store.clear(contact.contact_id)
            synchronized += 1

        self._latest_result = ContactSyncResult(
            attempted=attempted,
            synchronized=synchronized,
            failed=failed,
        )
        return self._latest_result

    def _eligible_contacts(self, *, force_failed: bool) -> list[Contact]:
        contacts = self._repository.list_synchronization_eligible(
            SynchronizationState.PENDING,
            limit=self._batch_size,
        )
        remaining = self._batch_size - len(contacts)
        if remaining <= 0:
            return contacts

        if force_failed:
            contacts.extend(
                self._repository.list_synchronization_eligible(
                    SynchronizationState.FAILED,
                    limit=remaining,
                )
            )
            return contacts

        if self._retry_store is None:
            return contacts
        for contact_id in self._retry_store.list_due_contact_ids(
            self._timestamp(),
            limit=remaining,
        ):
            contact = self._repository.get(contact_id)
            if contact is not None and contact.enrichment_state is ContactEnrichmentState.READY:
                contacts.append(contact)
        return contacts

    def _timestamp(self) -> datetime:
        timestamp = self._clock()
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("Contact synchronization clock must be timezone-aware.")
        return timestamp.astimezone(UTC)
