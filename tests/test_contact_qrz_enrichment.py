"""Tests for restart-safe background QRZ contact enrichment."""

from datetime import UTC, datetime
from uuid import UUID

from rolling_thunder.contact_qrz_enrichment import (
    ContactQrzEnrichmentResult,
    ContactQrzEnrichmentService,
)
from rolling_thunder.domain import (
    Contact,
    ContactEnrichmentState,
    ContactGridSource,
    RadioMode,
)
from rolling_thunder.qrz_xml import (
    QrzCallsignProfile,
    QrzConnectionError,
)
from rolling_thunder.radio_polling import PollCallback
from rolling_thunder.storage import StorageError


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


class MemoryRepository:
    def __init__(self, contacts: list[Contact]) -> None:
        self.contacts = {contact.contact_id: contact for contact in contacts}
        self.list_calls: list[tuple[ContactEnrichmentState, int]] = []
        self.completed: list[UUID] = []

    def list_by_enrichment_state(
        self,
        state: ContactEnrichmentState,
        *,
        limit: int = 100,
    ) -> list[Contact]:
        self.list_calls.append((state, limit))
        return [contact for contact in self.contacts.values() if contact.enrichment_state is state][
            :limit
        ]

    def complete_enrichment(
        self,
        contact_id: UUID,
        *,
        grid: str | None,
        grid_source: ContactGridSource | None,
    ) -> Contact:
        current = self.contacts[contact_id]
        completed = Contact.model_validate(
            {
                **current.model_dump(mode="python"),
                "grid": grid,
                "grid_source": grid_source,
                "enrichment_state": ContactEnrichmentState.READY,
            }
        )
        self.contacts[contact_id] = completed
        self.completed.append(contact_id)
        return completed


class FailingListRepository(MemoryRepository):
    def list_by_enrichment_state(
        self,
        state: ContactEnrichmentState,
        *,
        limit: int = 100,
    ) -> list[Contact]:
        del state, limit
        raise StorageError("database unavailable")


class FailingCompleteRepository(MemoryRepository):
    def complete_enrichment(
        self,
        contact_id: UUID,
        *,
        grid: str | None,
        grid_source: ContactGridSource | None,
    ) -> Contact:
        del contact_id, grid, grid_source
        raise StorageError("database update failed")


class FakeProvider:
    def __init__(
        self,
        result: QrzCallsignProfile | None = None,
        error: QrzConnectionError | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls: list[str] = []

    def lookup_profile(
        self,
        callsign: str,
    ) -> QrzCallsignProfile | None:
        self.calls.append(callsign)
        if self.error is not None:
            raise self.error
        return self.result


def pending_contact(
    contact_id: str = "00000000-0000-0000-0000-000000000201",
) -> Contact:
    return Contact(
        contact_id=UUID(contact_id),
        callsign="KI5VNB",
        frequency_hz=14_250_000,
        mode=RadioMode.USB,
        started_at=datetime(2026, 8, 2, 22, 0, tzinfo=UTC),
        rst_sent="59",
        rst_received="59",
        enrichment_state=ContactEnrichmentState.PENDING_QRZ,
    )


def profile(
    grid: str | None = "EM79xm",
) -> QrzCallsignProfile:
    return QrzCallsignProfile(
        callsign="KI5VNB",
        name="Geoff Kline",
        image_url=None,
        grid=grid,
    )


def test_start_schedules_without_immediate_network_lookup() -> None:
    repository = MemoryRepository([pending_contact()])
    provider = FakeProvider(profile())
    scheduler = ManualScheduler()
    service = ContactQrzEnrichmentService(
        repository,
        provider,
        scheduler,
    )

    result = service.start()

    assert result == ContactQrzEnrichmentResult()
    assert service.is_running is True
    assert scheduler.interval_s == 1.0
    assert provider.calls == []
    assert repository.list_calls == []

    service.stop()
    assert service.is_running is False
    assert scheduler.poll is not None
    assert scheduler.poll.cancelled is True


def test_scheduled_run_applies_qrz_grid_and_marks_ready() -> None:
    pending = pending_contact()
    repository = MemoryRepository([pending])
    provider = FakeProvider(profile())
    scheduler = ManualScheduler()
    service = ContactQrzEnrichmentService(
        repository,
        provider,
        scheduler,
    )
    service.start()

    scheduler.fire()

    completed = repository.contacts[pending.contact_id]
    assert provider.calls == ["KI5VNB"]
    assert completed.grid == "EM79xm"
    assert completed.grid_source is ContactGridSource.QRZ
    assert completed.enrichment_state is ContactEnrichmentState.READY
    assert service.latest_result == ContactQrzEnrichmentResult(
        attempted=1,
        completed=1,
        enriched_with_grid=1,
        storage_failures=0,
    )


def test_no_qrz_result_releases_contact_without_grid() -> None:
    pending = pending_contact()
    repository = MemoryRepository([pending])
    service = ContactQrzEnrichmentService(
        repository,
        FakeProvider(None),
        ManualScheduler(),
    )

    result = service.enrich_now()

    completed = repository.contacts[pending.contact_id]
    assert completed.grid is None
    assert completed.grid_source is None
    assert completed.enrichment_state is ContactEnrichmentState.READY
    assert result.completed == 1
    assert result.enriched_with_grid == 0


def test_invalid_qrz_grid_releases_contact_without_grid() -> None:
    pending = pending_contact()
    repository = MemoryRepository([pending])
    service = ContactQrzEnrichmentService(
        repository,
        FakeProvider(profile(grid=None)),
        ManualScheduler(),
    )

    result = service.enrich_now()

    completed = repository.contacts[pending.contact_id]
    assert completed.grid is None
    assert completed.enrichment_state is ContactEnrichmentState.READY
    assert result.completed == 1


def test_qrz_error_releases_contact_without_blocking_sync() -> None:
    pending = pending_contact()
    repository = MemoryRepository([pending])
    service = ContactQrzEnrichmentService(
        repository,
        FakeProvider(error=QrzConnectionError("QRZ callsign lookup could not be completed.")),
        ManualScheduler(),
    )

    result = service.enrich_now()

    completed = repository.contacts[pending.contact_id]
    assert completed.grid is None
    assert completed.grid_source is None
    assert completed.enrichment_state is ContactEnrichmentState.READY
    assert result == ContactQrzEnrichmentResult(
        attempted=1,
        completed=1,
        enriched_with_grid=0,
        storage_failures=0,
    )


def test_repository_list_failure_is_contained() -> None:
    service = ContactQrzEnrichmentService(
        FailingListRepository([]),
        FakeProvider(profile()),
        ManualScheduler(),
    )

    result = service.enrich_now()

    assert result == ContactQrzEnrichmentResult(
        storage_failures=1,
    )


def test_repository_completion_failure_leaves_contact_retryable() -> None:
    pending = pending_contact()
    repository = FailingCompleteRepository([pending])
    service = ContactQrzEnrichmentService(
        repository,
        FakeProvider(profile()),
        ManualScheduler(),
    )

    result = service.enrich_now()

    assert (
        repository.contacts[pending.contact_id].enrichment_state
        is ContactEnrichmentState.PENDING_QRZ
    )
    assert result == ContactQrzEnrichmentResult(
        attempted=1,
        completed=0,
        enriched_with_grid=0,
        storage_failures=1,
    )


def test_batch_size_bounds_each_enrichment_run() -> None:
    contacts = [pending_contact(f"00000000-0000-0000-0000-{index:012d}") for index in range(1, 4)]
    repository = MemoryRepository(contacts)
    provider = FakeProvider(profile())
    service = ContactQrzEnrichmentService(
        repository,
        provider,
        ManualScheduler(),
        batch_size=2,
    )

    result = service.enrich_now()

    assert result.attempted == 2
    assert len(provider.calls) == 2
    assert repository.list_calls == [(ContactEnrichmentState.PENDING_QRZ, 2)]
