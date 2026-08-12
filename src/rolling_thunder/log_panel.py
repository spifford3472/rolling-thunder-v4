"""Background-backed mobile Log panel state, manual synchronization, and retention."""

from __future__ import annotations

import sqlite3
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Protocol

from rolling_thunder.callsign_country import callsign_country_abbreviation
from rolling_thunder.contact_sync import ContactSyncResult
from rolling_thunder.domain import Frequency, SynchronizationState
from rolling_thunder.radio_band import RadioBandResolutionError, resolve_radio_band
from rolling_thunder.radio_polling import PollScheduler, ScheduledPoll
from rolling_thunder.storage import StorageError, initialize_database
from rolling_thunder.threading_scheduler import ThreadingPollScheduler

_LOG_PANEL_LIMIT = 10
_DEFAULT_MAX_CONTACTS = 5_000
_DEFAULT_PRUNE_BATCH = 1_000


class LogSyncCommands(Protocol):
    """Synchronous contact-sync boundary invoked only from a worker thread."""

    def synchronize_unsynchronized_now(self) -> ContactSyncResult:
        """Synchronize pending and failed contacts immediately."""
        ...


@dataclass(frozen=True, slots=True)
class LogPanelRow:
    """One glanceable local contact row."""

    started_at: datetime
    callsign: str
    band: str
    country: str
    synchronization_state: SynchronizationState

    @property
    def status_text(self) -> str:
        """Return non-color-only synchronization semantics."""
        return {
            SynchronizationState.SYNCHRONIZED: "✓ SYNC",
            SynchronizationState.PENDING: "○ WAIT",
            SynchronizationState.FAILED: "! FAIL",
        }[self.synchronization_state]


@dataclass(frozen=True, slots=True)
class LogPanelSnapshot:
    """Immutable UI snapshot; reading it performs no database or network work."""

    rows: tuple[LogPanelRow, ...] = ()
    unsynchronized_count: int = 0
    total_count: int = 0
    syncing: bool = False
    status_text: str = "READY"

    @property
    def summary_text(self) -> str:
        return f"UNSYNCED {self.unsynchronized_count} / TOTAL {self.total_count}"


class ContactLogRepository:
    """Explicit read/retention repository over the authoritative local contact database."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        initialize_database(database_path)

    def read_panel_state(self, *, limit: int = _LOG_PANEL_LIMIT) -> LogPanelSnapshot:
        """Read newest contacts and aggregate counts in one short local transaction."""
        if limit < 1 or limit > 100:
            raise ValueError("Log panel limit must be between 1 and 100.")
        try:
            with sqlite3.connect(self._database_path) as connection:
                connection.row_factory = sqlite3.Row
                total = int(connection.execute("SELECT COUNT(*) FROM contacts").fetchone()[0])
                unsynchronized = int(
                    connection.execute(
                        """
                        SELECT COUNT(*)
                        FROM contacts
                        WHERE synchronization_state <> 'synchronized'
                        """
                    ).fetchone()[0]
                )
                rows = connection.execute(
                    """
                    SELECT callsign, frequency_hz, started_at, synchronization_state
                    FROM contacts
                    ORDER BY started_at DESC, contact_id ASC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        except sqlite3.Error as error:
            raise StorageError(
                f"Log panel state could not be read from {self._database_path}: {error}"
            ) from error

        return LogPanelSnapshot(
            rows=tuple(self._row_from_sql(row) for row in rows),
            unsynchronized_count=unsynchronized,
            total_count=total,
        )

    def prune_synchronized_contacts(
        self,
        *,
        maximum_contacts: int = _DEFAULT_MAX_CONTACTS,
        prune_batch: int = _DEFAULT_PRUNE_BATCH,
    ) -> int:
        """Transactionally prune oldest proven-synchronized contacts only when over limit."""
        if maximum_contacts < 1 or prune_batch < 1:
            raise ValueError("Retention limits must be positive.")
        try:
            with sqlite3.connect(self._database_path) as connection:
                connection.execute("PRAGMA foreign_keys = ON")
                connection.execute("BEGIN IMMEDIATE")
                total = int(connection.execute("SELECT COUNT(*) FROM contacts").fetchone()[0])
                if total <= maximum_contacts:
                    connection.commit()
                    return 0

                rows = connection.execute(
                    """
                    SELECT contact_id
                    FROM contacts
                    WHERE synchronization_state = 'synchronized'
                    ORDER BY started_at ASC, contact_id ASC
                    LIMIT ?
                    """,
                    (prune_batch,),
                ).fetchall()
                contact_ids = [str(row[0]) for row in rows]
                if not contact_ids:
                    connection.commit()
                    return 0

                placeholders = ",".join("?" for _ in contact_ids)
                result = connection.execute(
                    f"""
                    DELETE FROM contacts
                    WHERE synchronization_state = 'synchronized'
                      AND contact_id IN ({placeholders})
                    """,
                    contact_ids,
                )
                connection.commit()
                return result.rowcount
        except sqlite3.Error as error:
            raise StorageError(
                f"Local synchronized-contact retention failed in {self._database_path}: {error}"
            ) from error

    @staticmethod
    def _row_from_sql(row: sqlite3.Row) -> LogPanelRow:
        frequency = Frequency(hz=int(row["frequency_hz"]))
        try:
            band = resolve_radio_band(frequency).value.upper()
        except RadioBandResolutionError:
            band = "—"
        started_at = datetime.fromisoformat(str(row["started_at"])).astimezone(UTC)
        return LogPanelRow(
            started_at=started_at,
            callsign=str(row["callsign"]),
            band=band,
            country=callsign_country_abbreviation(str(row["callsign"])),
            synchronization_state=SynchronizationState(str(row["synchronization_state"])),
        )


class LogPanelController:
    """Publish immutable log snapshots while keeping DB/network work off Tk."""

    def __init__(
        self,
        repository: ContactLogRepository,
        sync: LogSyncCommands | None,
        *,
        scheduler: PollScheduler | None = None,
        executor: Executor | None = None,
        refresh_interval_s: float = 1.0,
    ) -> None:
        if refresh_interval_s <= 0:
            raise ValueError("Log panel refresh interval must be positive.")
        self._repository = repository
        self._sync = sync
        self._scheduler = scheduler or ThreadingPollScheduler()
        self._executor = executor or ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="rolling-thunder-log-sync",
        )
        self._owns_executor = executor is None
        self._refresh_interval_s = refresh_interval_s
        self._lock = Lock()
        self._snapshot = LogPanelSnapshot(
            status_text="SYNC DISABLED" if sync is None else "READY"
        )
        self._scheduled_poll: ScheduledPoll | None = None
        self._sync_future: Future[object] | None = None
        self._seen_initial_state = False

    @property
    def latest_state(self) -> LogPanelSnapshot:
        """Return the latest immutable snapshot without I/O."""
        with self._lock:
            return self._snapshot

    def start(self) -> LogPanelSnapshot:
        """Start local refresh and opportunistic synchronization background work."""
        if self._scheduled_poll is not None:
            raise RuntimeError("Log panel controller is already running.")
        self._refresh_local()
        self._scheduled_poll = self._scheduler.schedule_repeating(
            self._refresh_interval_s,
            self._refresh_local,
        )
        return self.latest_state

    def stop(self) -> LogPanelSnapshot:
        """Stop refreshes and release the owned worker executor."""
        scheduled = self._scheduled_poll
        self._scheduled_poll = None
        if scheduled is not None:
            scheduled.cancel()
        if self._owns_executor and isinstance(self._executor, ThreadPoolExecutor):
            self._executor.shutdown(wait=False, cancel_futures=False)
        return self.latest_state

    def request_sync(self) -> bool:
        """Submit exactly one manual/opportunistic sync request and return immediately."""
        if self._sync is None:
            self._set_status("SYNC DISABLED", syncing=False)
            return False
        with self._lock:
            future = self._sync_future
            if future is not None and not future.done():
                return False
            self._snapshot = self._with_status(self._snapshot, "SYNCING…", syncing=True)
            self._sync_future = self._executor.submit(self._run_sync)
        return True

    def _run_sync(self) -> None:
        sync = self._sync
        if sync is None:
            return
        try:
            result = sync.synchronize_unsynchronized_now()
        except (StorageError, ValueError) as error:
            self._set_status(f"SYNC ERROR: {error}"[:120], syncing=False)
            self._refresh_local(preserve_status=True)
            return

        if result.failed:
            status = f"SYNC FAILED {result.failed}"
        elif result.synchronized:
            status = f"SYNCED {result.synchronized}"
        elif self.latest_state.unsynchronized_count:
            status = "SOME STILL PENDING"
        else:
            status = "SYNCHRONIZED"
        self._set_status(status, syncing=False)
        self._refresh_local(preserve_status=True)

    def _refresh_local(self, *, preserve_status: bool = False) -> None:
        try:
            fresh = self._repository.read_panel_state()
            if fresh.total_count > _DEFAULT_MAX_CONTACTS:
                self._repository.prune_synchronized_contacts()
                fresh = self._repository.read_panel_state()
        except StorageError as error:
            self._set_status(f"LOG DB ERROR: {error}"[:120], syncing=False)
            return

        with self._lock:
            current = self._snapshot
            should_sync = (
                self._sync is not None
                and fresh.unsynchronized_count > 0
                and not current.syncing
                and (
                    not self._seen_initial_state
                    or fresh.total_count > current.total_count
                    or fresh.unsynchronized_count > current.unsynchronized_count
                )
            )
            self._seen_initial_state = True
            status = current.status_text if preserve_status else self._routine_status(fresh, current)
            self._snapshot = LogPanelSnapshot(
                rows=fresh.rows,
                unsynchronized_count=fresh.unsynchronized_count,
                total_count=fresh.total_count,
                syncing=current.syncing,
                status_text=status,
            )
        if should_sync:
            self.request_sync()

    def _set_status(self, text: str, *, syncing: bool) -> None:
        with self._lock:
            self._snapshot = self._with_status(self._snapshot, text, syncing=syncing)

    @staticmethod
    def _routine_status(fresh: LogPanelSnapshot, current: LogPanelSnapshot) -> str:
        if current.syncing:
            return current.status_text
        if fresh.unsynchronized_count:
            return "UNSYNCED CONTACTS"
        return "SYNCHRONIZED" if fresh.total_count else "READY"

    @staticmethod
    def _with_status(
        snapshot: LogPanelSnapshot,
        text: str,
        *,
        syncing: bool,
    ) -> LogPanelSnapshot:
        return LogPanelSnapshot(
            rows=snapshot.rows,
            unsynchronized_count=snapshot.unsynchronized_count,
            total_count=snapshot.total_count,
            syncing=syncing,
            status_text=text,
        )
