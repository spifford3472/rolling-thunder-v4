"""Focused tests for operator-forced versus automatic contact retry behavior."""

from datetime import UTC, datetime
from uuid import UUID

from rolling_thunder.contact_sync import ContactSyncService
from rolling_thunder.domain import Contact, RadioMode, SynchronizationState
from rolling_thunder.mock_home_platform import MockHomePlatformClient
from rolling_thunder.radio_polling import PollCallback


class ManualScheduledPoll:
    def __init__(self, callback: PollCallback) -> None:
        self._callback = callback

    def cancel(self) -> None:
        pass

    def fire(self) -> None:
        self._callback()


class ManualScheduler:
    def __init__(self) -> None:
        self.poll: ManualScheduledPoll | None = None

    def schedule_repeating(self, interval_s: float, callback: PollCallback) -> ManualScheduledPoll:
        assert interval_s > 0
        self.poll = ManualScheduledPoll(callback)
        return self.poll


class FailedContactRepository:
    def __init__(self, contact: Contact) -> None:
        self.contact = contact

    def get(self, contact_id: UUID) -> Contact | None:
        return self.contact if contact_id == self.contact.contact_id else None

    def list_synchronization_eligible(
        self,
        state: SynchronizationState,
        *,
        limit: int = 100,
    ) -> list[Contact]:
        if self.contact.synchronization_state is state and limit > 0:
            return [self.contact]
        return []

    def update_synchronization_state(
        self,
        contact_id: UUID,
        state: SynchronizationState,
    ) -> Contact:
        assert contact_id == self.contact.contact_id
        self.contact = self.contact.model_copy(update={"synchronization_state": state})
        return self.contact


class FutureRetryStore:
    """Retry metadata whose failed contact is deliberately not due yet."""

    def __init__(self) -> None:
        self.due_queries = 0
        self.cleared: list[UUID] = []

    def list_due_contact_ids(self, due_at: datetime, *, limit: int) -> list[UUID]:
        del due_at, limit
        self.due_queries += 1
        return []

    def record_failure(
        self,
        contact_id: UUID,
        *,
        failed_at: datetime,
        error_message: str,
        initial_delay_s: float,
        max_delay_s: float,
    ) -> object:
        del contact_id, failed_at, error_message, initial_delay_s, max_delay_s
        return object()

    def clear(self, contact_id: UUID) -> None:
        self.cleared.append(contact_id)


def test_manual_sync_retries_failed_contact_before_automatic_backoff_is_due() -> None:
    now = datetime(2026, 8, 12, 20, 0, tzinfo=UTC)
    failed = Contact(
        contact_id="11111111-2222-3333-4444-555555555555",
        callsign="W1AW",
        frequency_hz=14_250_000,
        mode=RadioMode.USB,
        started_at=now,
        rst_sent="59",
        rst_received="59",
        synchronization_state=SynchronizationState.FAILED,
    )
    repository = FailedContactRepository(failed)
    retry_store = FutureRetryStore()
    client = MockHomePlatformClient(clock=lambda: now)
    scheduler = ManualScheduler()
    service = ContactSyncService(
        repository,
        client,
        scheduler,
        retry_store=retry_store,
        clock=lambda: now,
    )
    service.start()
    assert scheduler.poll is not None

    scheduler.poll.fire()

    assert service.latest_result.attempted == 0
    assert repository.contact.synchronization_state is SynchronizationState.FAILED
    assert retry_store.due_queries == 1

    result = service.synchronize_now()

    assert result.attempted == 1
    assert result.synchronized == 1
    assert result.failed == 0
    assert repository.contact.synchronization_state is SynchronizationState.SYNCHRONIZED
    assert retry_store.cleared == [failed.contact_id]
