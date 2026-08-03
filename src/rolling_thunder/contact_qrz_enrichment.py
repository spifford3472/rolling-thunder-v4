"""Restart-safe background QRZ grid enrichment for committed contacts."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from rolling_thunder.domain import (
    Contact,
    ContactEnrichmentState,
    ContactGridSource,
)
from rolling_thunder.qrz_xml import QrzCallsignProfile, QrzLookupError
from rolling_thunder.radio_polling import PollScheduler, ScheduledPoll
from rolling_thunder.storage import StorageError
from rolling_thunder.value_types import MaidenheadGrid


class ContactQrzProfileProvider(Protocol):
    """Look up one optional QRZ callsign profile."""

    def lookup_profile(
        self,
        callsign: str,
    ) -> QrzCallsignProfile | None:
        """Return one QRZ profile, or none when no record exists."""
        ...


class ContactQrzEnrichmentRepository(Protocol):
    """Persistence operations required by QRZ enrichment."""

    def list_by_enrichment_state(
        self,
        state: ContactEnrichmentState,
        *,
        limit: int = 100,
    ) -> list[Contact]:
        """List contacts awaiting one enrichment state."""
        ...

    def complete_enrichment(
        self,
        contact_id: UUID,
        *,
        grid: MaidenheadGrid | None,
        grid_source: ContactGridSource | None,
    ) -> Contact:
        """Atomically complete optional contacted-grid enrichment."""
        ...


@dataclass(frozen=True, slots=True)
class ContactQrzEnrichmentResult:
    """Summary of one bounded QRZ enrichment run."""

    attempted: int = 0
    completed: int = 0
    enriched_with_grid: int = 0
    storage_failures: int = 0


class ContactQrzEnrichmentService:
    """Resolve pending QRZ grids outside the durable Commit path."""

    def __init__(
        self,
        repository: ContactQrzEnrichmentRepository,
        provider: ContactQrzProfileProvider,
        scheduler: PollScheduler,
        *,
        interval_s: float = 1.0,
        batch_size: int = 25,
    ) -> None:
        if interval_s <= 0:
            raise ValueError("QRZ enrichment interval must be positive.")
        if batch_size <= 0:
            raise ValueError("QRZ enrichment batch size must be positive.")

        self._repository = repository
        self._provider = provider
        self._scheduler = scheduler
        self._interval_s = interval_s
        self._batch_size = batch_size
        self._scheduled_poll: ScheduledPoll | None = None
        self._processing = False
        self._latest_result = ContactQrzEnrichmentResult()

    @property
    def is_running(self) -> bool:
        """Return whether future enrichment runs are scheduled."""
        return self._scheduled_poll is not None

    @property
    def latest_result(self) -> ContactQrzEnrichmentResult:
        """Return the latest immutable enrichment summary."""
        return self._latest_result

    def start(self) -> ContactQrzEnrichmentResult:
        """Schedule enrichment without performing startup network I/O."""
        if self.is_running:
            raise RuntimeError("Contact QRZ enrichment service is already running.")

        self._scheduled_poll = self._scheduler.schedule_repeating(
            self._interval_s,
            self._enrich_scheduled,
        )
        return self._latest_result

    def stop(self) -> ContactQrzEnrichmentResult:
        """Stop future enrichment runs."""
        scheduled_poll = self._scheduled_poll
        self._scheduled_poll = None
        if scheduled_poll is not None:
            scheduled_poll.cancel()
        return self._latest_result

    def enrich_now(self) -> ContactQrzEnrichmentResult:
        """Process one bounded batch unless another run is active."""
        if self._processing:
            return self._latest_result
        return self._run_once()

    def _enrich_scheduled(self) -> None:
        if not self.is_running or self._processing:
            return
        self._run_once()

    def _run_once(self) -> ContactQrzEnrichmentResult:
        self._processing = True
        attempted = 0
        completed = 0
        enriched_with_grid = 0
        storage_failures = 0

        try:
            try:
                contacts = self._repository.list_by_enrichment_state(
                    ContactEnrichmentState.PENDING_QRZ,
                    limit=self._batch_size,
                )
            except StorageError:
                self._latest_result = ContactQrzEnrichmentResult(
                    storage_failures=1,
                )
                return self._latest_result

            for contact in contacts:
                attempted += 1
                grid: MaidenheadGrid | None = None

                try:
                    profile = self._provider.lookup_profile(str(contact.callsign))
                except QrzLookupError:
                    profile = None

                if profile is not None:
                    grid = profile.grid

                grid_source = ContactGridSource.QRZ if grid is not None else None

                try:
                    self._repository.complete_enrichment(
                        contact.contact_id,
                        grid=grid,
                        grid_source=grid_source,
                    )
                except StorageError:
                    storage_failures += 1
                    continue

                completed += 1
                if grid is not None:
                    enriched_with_grid += 1

            self._latest_result = ContactQrzEnrichmentResult(
                attempted=attempted,
                completed=completed,
                enriched_with_grid=enriched_with_grid,
                storage_failures=storage_failures,
            )
            return self._latest_result
        finally:
            self._processing = False
