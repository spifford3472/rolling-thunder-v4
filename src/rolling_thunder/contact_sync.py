"""Deterministic synchronization of locally stored contacts."""

from typing import Protocol

from pydantic import Field

from rolling_thunder.domain import Contact, DomainModel, SynchronizationState
from rolling_thunder.home_platform import (
    ContactUploadRequest,
    HomePlatformClient,
    HomePlatformError,
)
from rolling_thunder.radio_polling import PollScheduler, ScheduledPoll


class ContactSyncRepository(Protocol):
    """Persistence operations required by the synchronization service."""

    def list_by_synchronization_state(
        self,
        state: SynchronizationState,
        *,
        limit: int = 100,
    ) -> list[Contact]:
        """Return contacts matching one synchronization state."""
        ...

    def update_synchronization_state(
        self,
        contact_id: object,
        state: SynchronizationState,
    ) -> Contact:
        """Persist and return a contact's new synchronization state."""
        ...


class ContactSyncResult(DomainModel):
    """Immutable summary of one synchronization run."""

    attempted: int = Field(ge=0)
    synchronized: int = Field(ge=0)
    failed: int = Field(ge=0)


class ContactSyncService:
    """Upload pending contacts without coupling network failures to local logging."""

    def __init__(
        self,
        repository: ContactSyncRepository,
        client: HomePlatformClient,
        scheduler: PollScheduler,
        *,
        interval_s: float = 30.0,
        batch_size: int = 25,
    ) -> None:
        if interval_s <= 0:
            raise ValueError("Contact synchronization interval must be positive.")
        if batch_size <= 0:
            raise ValueError("Contact synchronization batch size must be positive.")

        self._repository = repository
        self._client = client
        self._scheduler = scheduler
        self._interval_s = interval_s
        self._batch_size = batch_size
        self._scheduled_poll: ScheduledPoll | None = None
        self._synchronizing = False
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
        """Synchronize one bounded pending batch unless a run is already active."""
        if self._synchronizing:
            return self._latest_result
        return self._run_once()

    def _synchronize_once(self) -> None:
        if not self.is_running or self._synchronizing:
            return
        self._run_once()

    def _run_once(self) -> ContactSyncResult:
        self._synchronizing = True
        attempted = 0
        synchronized = 0
        failed = 0
        try:
            contacts = self._repository.list_by_synchronization_state(
                SynchronizationState.PENDING,
                limit=self._batch_size,
            )
            for contact in contacts:
                attempted += 1
                try:
                    self._client.upload_contact(ContactUploadRequest(contact=contact))
                except HomePlatformError:
                    self._repository.update_synchronization_state(
                        contact.contact_id,
                        SynchronizationState.FAILED,
                    )
                    failed += 1
                    continue

                self._repository.update_synchronization_state(
                    contact.contact_id,
                    SynchronizationState.SYNCHRONIZED,
                )
                synchronized += 1

            self._latest_result = ContactSyncResult(
                attempted=attempted,
                synchronized=synchronized,
                failed=failed,
            )
            return self._latest_result
        finally:
            self._synchronizing = False
