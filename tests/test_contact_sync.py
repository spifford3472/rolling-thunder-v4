"""Tests for deterministic contact synchronization."""

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

import pytest

from rolling_thunder.contact_sync import ContactSyncResult, ContactSyncService
from rolling_thunder.domain import (
    Contact,
    ContactEnrichmentState,
    RadioMode,
    SynchronizationState,
)
from rolling_thunder.home_platform import ContactUploadRequest, ContactUploadResult
from rolling_thunder.mock_home_platform import MockHomePlatformClient
from rolling_thunder.radio_polling import PollCallback


class ManualScheduledPoll:
    def __init__(self, callback: PollCallback) -> None:
        self.callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True

    def fire(self) -> None:
        if not self.cancelled:
            self.callback()


class ManualScheduler:
    def __init__(self) -> None:
        self.interval_s: float | None = None
        self.poll: ManualScheduledPoll | None = None

    def schedule_repeating(
        self,
        interval_s: float,
        callback: PollCallback,
    ) -> ManualScheduledPoll:
        self.interval_s = interval_s
        self.poll = ManualScheduledPoll(callback)
        return self.poll

    def fire(self) -> None:
        assert self.poll is not None
        self.poll.fire()


class MemoryContactRepository:
    def __init__(self, contacts: list[Contact]) -> None:
        self.contacts = {contact.contact_id: contact for contact in contacts}
        self.list_calls: list[tuple[SynchronizationState, int]] = []
        self.updated_states: list[tuple[UUID, SynchronizationState]] = []

    def list_synchronization_eligible(
        self,
        state: SynchronizationState,
        *,
        limit: int = 100,
    ) -> list[Contact]:
        self.list_calls.append((state, limit))
        return [
            contact
            for contact in self.contacts.values()
            if (
                contact.synchronization_state is state
                and contact.enrichment_state is ContactEnrichmentState.READY
            )
        ][:limit]

    def update_synchronization_state(
        self,
        contact_id: UUID,
        state: SynchronizationState,
    ) -> Contact:
        current = self.contacts[contact_id]
        updated = current.model_copy(update={"synchronization_state": state})
        self.contacts[contact_id] = updated
        self.updated_states.append((contact_id, state))
        return updated


def timestamp() -> datetime:
    return datetime(2026, 7, 26, 15, 0, tzinfo=UTC)


def contact(contact_id: str, callsign: str = "W8O") -> Contact:
    return Contact(
        contact_id=UUID(contact_id),
        callsign=callsign,
        frequency_hz=14_250_000,
        mode=RadioMode.USB,
        started_at=timestamp(),
        rst_sent="59",
        rst_received="59",
        synchronization_state=SynchronizationState.PENDING,
    )


def build_service(
    repository: MemoryContactRepository,
    client: MockHomePlatformClient,
    *,
    interval_s: float = 20.0,
    batch_size: int = 25,
) -> tuple[ContactSyncService, ManualScheduler]:
    scheduler = ManualScheduler()
    service = ContactSyncService(
        repository,
        client,
        scheduler,
        interval_s=interval_s,
        batch_size=batch_size,
    )
    return service, scheduler


def test_service_starts_without_immediate_repository_or_network_work() -> None:
    repository = MemoryContactRepository([])
    client = MockHomePlatformClient(clock=timestamp)
    service, scheduler = build_service(repository, client)

    result = service.start()

    assert result == ContactSyncResult(attempted=0, synchronized=0, failed=0)
    assert service.is_running is True
    assert scheduler.interval_s == 20.0
    assert repository.list_calls == []


def test_scheduled_run_synchronizes_pending_contacts() -> None:
    first = contact("11111111-1111-1111-1111-111111111111")
    second = contact("22222222-2222-2222-2222-222222222222", "KI5VNB")
    repository = MemoryContactRepository([first, second])
    client = MockHomePlatformClient(clock=timestamp)
    service, scheduler = build_service(repository, client)
    service.start()

    scheduler.fire()

    assert service.latest_result == ContactSyncResult(
        attempted=2,
        synchronized=2,
        failed=0,
    )
    assert repository.list_calls == [(SynchronizationState.PENDING, 25)]
    assert repository.updated_states == [
        (first.contact_id, SynchronizationState.SYNCHRONIZED),
        (second.contact_id, SynchronizationState.SYNCHRONIZED),
    ]


def test_pending_qrz_contact_is_not_uploaded() -> None:
    pending = contact("33333333-3333-3333-3333-333333333330").model_copy(
        update={
            "enrichment_state": ContactEnrichmentState.PENDING_QRZ,
        }
    )
    repository = MemoryContactRepository([pending])
    client = MockHomePlatformClient(clock=timestamp)
    service, _ = build_service(repository, client)

    result = service.synchronize_now()

    assert result == ContactSyncResult(
        attempted=0,
        synchronized=0,
        failed=0,
    )
    assert repository.updated_states == []


def test_already_existing_remote_contact_is_synchronized() -> None:
    pending = contact("33333333-3333-3333-3333-333333333333")
    repository = MemoryContactRepository([pending])
    client = MockHomePlatformClient(clock=timestamp)
    client.upload_contact(ContactUploadRequest(contact=pending))
    service, _ = build_service(repository, client)

    result = service.synchronize_now()

    assert result.synchronized == 1
    assert repository.contacts[pending.contact_id].synchronization_state is (
        SynchronizationState.SYNCHRONIZED
    )


def test_typed_platform_failure_marks_contact_failed_and_continues() -> None:
    first = contact("44444444-4444-4444-4444-444444444444")
    second = contact("55555555-5555-5555-5555-555555555555")
    repository = MemoryContactRepository([first, second])
    client = MockHomePlatformClient(clock=timestamp)
    client.fail_next_upload("temporary remote failure")
    service, _ = build_service(repository, client)

    result = service.synchronize_now()

    assert result == ContactSyncResult(attempted=2, synchronized=1, failed=1)
    assert repository.updated_states == [
        (first.contact_id, SynchronizationState.FAILED),
        (second.contact_id, SynchronizationState.SYNCHRONIZED),
    ]


def test_batch_size_limits_each_run() -> None:
    contacts = [contact(f"00000000-0000-0000-0000-{index:012d}") for index in range(1, 4)]
    repository = MemoryContactRepository(contacts)
    client = MockHomePlatformClient(clock=timestamp)
    service, _ = build_service(repository, client, batch_size=2)

    result = service.synchronize_now()

    assert result.attempted == 2
    assert len(repository.updated_states) == 2
    assert repository.list_calls == [(SynchronizationState.PENDING, 2)]


def test_overlapping_run_returns_previous_result_without_duplicate_upload() -> None:
    pending = contact("66666666-6666-6666-6666-666666666666")
    repository = MemoryContactRepository([pending])
    client = ReentrantClient(clock=timestamp)
    service, _ = build_service(repository, client)
    client.during_upload = service.synchronize_now

    result = service.synchronize_now()

    assert result == ContactSyncResult(attempted=1, synchronized=1, failed=0)
    assert client.upload_count == 1
    assert client.reentrant_result == ContactSyncResult(
        attempted=0,
        synchronized=0,
        failed=0,
    )


def test_stop_cancels_future_scheduled_runs() -> None:
    pending = contact("77777777-7777-7777-7777-777777777777")
    repository = MemoryContactRepository([pending])
    client = MockHomePlatformClient(clock=timestamp)
    service, scheduler = build_service(repository, client)
    service.start()

    service.stop()
    scheduler.fire()

    assert service.is_running is False
    assert repository.list_calls == []


@pytest.mark.parametrize(
    ("interval_s", "batch_size", "message"),
    [
        (0.0, 25, "interval"),
        (20.0, 0, "batch size"),
    ],
)
def test_invalid_settings_are_rejected(
    interval_s: float,
    batch_size: int,
    message: str,
) -> None:
    repository = MemoryContactRepository([])
    client = MockHomePlatformClient(clock=timestamp)

    with pytest.raises(ValueError, match=message):
        build_service(
            repository,
            client,
            interval_s=interval_s,
            batch_size=batch_size,
        )


class ReentrantClient(MockHomePlatformClient):
    def __init__(self, *, clock: Callable[[], datetime]) -> None:
        super().__init__(clock=clock)
        self.during_upload: Callable[[], ContactSyncResult] | None = None
        self.reentrant_result: ContactSyncResult | None = None
        self.upload_count = 0

    def upload_contact(self, request: ContactUploadRequest) -> ContactUploadResult:
        self.upload_count += 1
        if self.during_upload is not None:
            callback = self.during_upload
            self.during_upload = None
            self.reentrant_result = callback()
        return super().upload_contact(request)
