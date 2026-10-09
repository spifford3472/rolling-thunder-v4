"""Durable source-side fan-out for completed FT8 QSO analytics."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Protocol
from uuid import UUID

from pydantic import Field, field_validator

from rolling_thunder.domain import Contact, DomainModel
from rolling_thunder.forge_pskreporter_orchestration import CompletedFt8QsoEvent
from rolling_thunder.ft8.performance import FT8PerformanceAttempt

_MAX_BATCH_SIZE = 100
_MAX_ERROR_LENGTH = 1_000


class CompletedQsoProducerError(RuntimeError):
    """Raised when the local completed-QSO outbox cannot be used safely."""


class CompletedQsoProducerConflict(CompletedQsoProducerError):
    """Raised when one stable QSO UUID is reused with changed event data."""


class CompletedQsoProducerDisposition(StrEnum):
    ACCEPTED = "accepted"
    REPLAYED = "replayed"


class CompletedQsoDestination(StrEnum):
    VOACAP = "voacap"
    PSK_REPORTER = "psk_reporter"


class CompletedQsoDeliveryState(StrEnum):
    PENDING = "pending"
    RETRY = "retry"
    DELIVERED = "delivered"


class CompletedQsoOutboxItem(DomainModel):
    """One immutable event and its destination-specific delivery state."""

    event: CompletedFt8QsoEvent
    destination: CompletedQsoDestination
    state: CompletedQsoDeliveryState
    attempt_count: int = Field(ge=0)
    next_attempt_at_utc: datetime
    last_error: str | None = Field(default=None, max_length=_MAX_ERROR_LENGTH)

    @field_validator("next_attempt_at_utc")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return _utc(value)


class CompletedQsoVoacapSink(Protocol):
    """Authenticated VOACAP ingestion client owned by the later composition."""

    def enqueue(self, contact: Contact) -> object: ...


class CompletedFt8PskSink(Protocol):
    """Authenticated PSK event client owned by the later composition."""

    def enqueue(self, event: CompletedFt8QsoEvent) -> object: ...


class CompletedQsoCapture(Protocol):
    """Post-durability source boundary used by FT8 runtime composition."""

    def capture(
        self,
        contact: Contact,
        terminal_attempt: FT8PerformanceAttempt,
        *,
        captured_at_utc: datetime | None = None,
    ) -> CompletedQsoProducerDisposition: ...


class CompletedQsoProducerRepository:
    """SQLite outbox with exact replay and independent destination progress."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._initialize()

    def enqueue(
        self,
        event: CompletedFt8QsoEvent,
        *,
        captured_at_utc: datetime,
    ) -> CompletedQsoProducerDisposition:
        captured_at = _time(captured_at_utc)
        payload = event.model_dump_json()
        payload_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        contact_id = str(event.contact.contact_id)
        try:
            with sqlite3.connect(self._database_path) as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT event_sha256, event_json FROM completed_qso_producer_outbox "
                    "WHERE contact_id = ?",
                    (contact_id,),
                ).fetchone()
                if row is not None:
                    if row != (payload_hash, payload):
                        try:
                            existing = CompletedFt8QsoEvent.model_validate_json(row[1])
                        except ValueError as error:
                            raise CompletedQsoProducerError(
                                f"completed-QSO outbox contains invalid event {contact_id}"
                            ) from error
                        if existing != event:
                            raise CompletedQsoProducerConflict(
                                "completed-QSO producer UUID was reused with changed data: "
                                f"{contact_id}"
                            )
                    connection.commit()
                    return CompletedQsoProducerDisposition.REPLAYED
                connection.execute(
                    """
                    INSERT INTO completed_qso_producer_outbox (
                        contact_id, event_sha256, event_json, captured_at_utc,
                        voacap_state, voacap_next_attempt_at_utc,
                        psk_reporter_state, psk_reporter_next_attempt_at_utc
                    ) VALUES (?, ?, ?, ?, 'pending', ?, 'pending', ?)
                    """,
                    (
                        contact_id,
                        payload_hash,
                        payload,
                        captured_at,
                        captured_at,
                        captured_at,
                    ),
                )
                connection.commit()
        except CompletedQsoProducerError:
            raise
        except sqlite3.Error as error:
            raise CompletedQsoProducerError("completed-QSO event enqueue failed") from error
        return CompletedQsoProducerDisposition.ACCEPTED

    def list_due(
        self,
        destination: CompletedQsoDestination,
        *,
        now_utc: datetime,
        limit: int,
    ) -> tuple[CompletedQsoOutboxItem, ...]:
        if not 1 <= limit <= _MAX_BATCH_SIZE:
            raise ValueError(f"limit must be between 1 and {_MAX_BATCH_SIZE}")
        state_column, attempt_column, due_column, error_column = _columns(destination)
        query = f"""
            SELECT event_json, {state_column}, {attempt_column}, {due_column}, {error_column}
            FROM completed_qso_producer_outbox
            WHERE {state_column} IN ('pending', 'retry') AND {due_column} <= ?
            ORDER BY {due_column}, captured_at_utc, contact_id
            LIMIT ?
        """
        try:
            with sqlite3.connect(self._database_path) as connection:
                rows = connection.execute(query, (_time(now_utc), limit)).fetchall()
            return tuple(
                CompletedQsoOutboxItem(
                    event=CompletedFt8QsoEvent.model_validate_json(row[0]),
                    destination=destination,
                    state=CompletedQsoDeliveryState(row[1]),
                    attempt_count=int(row[2]),
                    next_attempt_at_utc=_parse_time(row[3]),
                    last_error=row[4],
                )
                for row in rows
            )
        except (sqlite3.Error, ValueError) as error:
            raise CompletedQsoProducerError("completed-QSO due events could not be read") from error

    def mark_delivered(
        self,
        contact_id: UUID,
        destination: CompletedQsoDestination,
    ) -> None:
        state_column, _attempt_column, due_column, error_column = _columns(destination)
        query = f"""
            UPDATE completed_qso_producer_outbox
            SET {state_column}='delivered', {due_column}=NULL, {error_column}=NULL,
                updated_at_utc=CURRENT_TIMESTAMP
            WHERE contact_id=? AND {state_column} IN ('pending', 'retry')
        """
        self._update_one(query, contact_id)

    def record_failure(
        self,
        contact_id: UUID,
        destination: CompletedQsoDestination,
        error: str,
        *,
        failed_at_utc: datetime,
        initial_delay: timedelta,
        maximum_delay: timedelta,
    ) -> None:
        if initial_delay <= timedelta(0) or maximum_delay < initial_delay:
            raise ValueError("retry durations must be positive and ordered")
        normalized_error = (error.strip() or "completed-QSO delivery failed")[:_MAX_ERROR_LENGTH]
        state_column, attempt_column, due_column, error_column = _columns(destination)
        try:
            with sqlite3.connect(self._database_path) as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    f"SELECT {attempt_column} FROM completed_qso_producer_outbox "
                    f"WHERE contact_id=? AND {state_column} IN ('pending', 'retry')",
                    (str(contact_id),),
                ).fetchone()
                if row is None:
                    raise CompletedQsoProducerError(
                        f"completed-QSO destination is not pending: {contact_id}"
                    )
                attempt_count = int(row[0]) + 1
                delay = min(maximum_delay, initial_delay * (2 ** (attempt_count - 1)))
                connection.execute(
                    f"""
                    UPDATE completed_qso_producer_outbox
                    SET {state_column}='retry', {attempt_column}=?, {due_column}=?,
                        {error_column}=?, updated_at_utc=CURRENT_TIMESTAMP
                    WHERE contact_id=?
                    """,
                    (
                        attempt_count,
                        _time(_utc(failed_at_utc) + delay),
                        normalized_error,
                        str(contact_id),
                    ),
                )
                connection.commit()
        except CompletedQsoProducerError:
            raise
        except sqlite3.Error as sqlite_error:
            raise CompletedQsoProducerError(
                "completed-QSO retry state could not be stored"
            ) from sqlite_error

    def state_for(
        self,
        contact_id: UUID,
        destination: CompletedQsoDestination,
    ) -> CompletedQsoDeliveryState | None:
        state_column, _attempt_column, _due_column, _error_column = _columns(destination)
        try:
            with sqlite3.connect(self._database_path) as connection:
                row = connection.execute(
                    f"SELECT {state_column} FROM completed_qso_producer_outbox "
                    "WHERE contact_id=?",
                    (str(contact_id),),
                ).fetchone()
        except sqlite3.Error as error:
            raise CompletedQsoProducerError("completed-QSO state could not be read") from error
        return None if row is None else CompletedQsoDeliveryState(row[0])

    def _update_one(self, query: str, contact_id: UUID) -> None:
        try:
            with sqlite3.connect(self._database_path) as connection:
                result = connection.execute(query, (str(contact_id),))
                if result.rowcount != 1:
                    raise CompletedQsoProducerError(
                        f"completed-QSO destination is not pending: {contact_id}"
                    )
                connection.commit()
        except CompletedQsoProducerError:
            raise
        except sqlite3.Error as error:
            raise CompletedQsoProducerError("completed-QSO state could not be updated") from error

    def _initialize(self) -> None:
        try:
            self._database_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self._database_path) as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS completed_qso_producer_outbox (
                        contact_id TEXT PRIMARY KEY,
                        event_sha256 TEXT NOT NULL CHECK(length(event_sha256) = 64),
                        event_json TEXT NOT NULL CHECK(length(event_json) >= 2),
                        captured_at_utc TEXT NOT NULL,
                        voacap_state TEXT NOT NULL CHECK(
                            voacap_state IN ('pending', 'retry', 'delivered')
                        ),
                        voacap_attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(
                            voacap_attempt_count >= 0
                        ),
                        voacap_next_attempt_at_utc TEXT,
                        voacap_last_error TEXT CHECK(
                            voacap_last_error IS NULL OR length(voacap_last_error) <= 1000
                        ),
                        psk_reporter_state TEXT NOT NULL CHECK(
                            psk_reporter_state IN ('pending', 'retry', 'delivered')
                        ),
                        psk_reporter_attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(
                            psk_reporter_attempt_count >= 0
                        ),
                        psk_reporter_next_attempt_at_utc TEXT,
                        psk_reporter_last_error TEXT CHECK(
                            psk_reporter_last_error IS NULL
                            OR length(psk_reporter_last_error) <= 1000
                        ),
                        created_at_utc TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at_utc TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS completed_qso_producer_voacap_due
                    ON completed_qso_producer_outbox (
                        voacap_state, voacap_next_attempt_at_utc, captured_at_utc
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS completed_qso_producer_psk_due
                    ON completed_qso_producer_outbox (
                        psk_reporter_state, psk_reporter_next_attempt_at_utc, captured_at_utc
                    )
                    """
                )
                connection.commit()
        except sqlite3.Error as error:
            raise CompletedQsoProducerError("completed-QSO outbox initialization failed") from error


class CompletedQsoPostDurabilityAdapter:
    """Attest and persist an event only after both source records are durable."""

    def __init__(
        self,
        repository: CompletedQsoProducerRepository,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._clock = clock

    def capture(
        self,
        contact: Contact,
        terminal_attempt: FT8PerformanceAttempt,
        *,
        captured_at_utc: datetime | None = None,
    ) -> CompletedQsoProducerDisposition:
        event = CompletedFt8QsoEvent(
            contact=contact,
            terminal_attempt=terminal_attempt,
        )
        captured_at = captured_at_utc or self._clock()
        return self._repository.enqueue(event, captured_at_utc=_utc(captured_at))


class CompletedQsoDeliveryWorker:
    """Perform bounded network fan-out from the already-durable local outbox."""

    def __init__(
        self,
        repository: CompletedQsoProducerRepository,
        *,
        voacap_sink: CompletedQsoVoacapSink | None = None,
        psk_reporter_sink: CompletedFt8PskSink | None = None,
        batch_size: int = 25,
        retry_initial_delay: timedelta = timedelta(seconds=5),
        retry_maximum_delay: timedelta = timedelta(minutes=5),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not 1 <= batch_size <= _MAX_BATCH_SIZE:
            raise ValueError(f"batch_size must be between 1 and {_MAX_BATCH_SIZE}")
        if retry_initial_delay <= timedelta(0) or retry_maximum_delay < retry_initial_delay:
            raise ValueError("retry durations must be positive and ordered")
        self._repository = repository
        self._voacap_sink = voacap_sink
        self._psk_reporter_sink = psk_reporter_sink
        self._batch_size = batch_size
        self._retry_initial_delay = retry_initial_delay
        self._retry_maximum_delay = retry_maximum_delay
        self._clock = clock

    def run_once(self) -> dict[CompletedQsoDestination, tuple[int, int]]:
        """Return attempted/delivered counts for each independently enabled sink."""
        results: dict[CompletedQsoDestination, tuple[int, int]] = {}
        if self._voacap_sink is not None:
            results[CompletedQsoDestination.VOACAP] = self._deliver(
                CompletedQsoDestination.VOACAP
            )
        if self._psk_reporter_sink is not None:
            results[CompletedQsoDestination.PSK_REPORTER] = self._deliver(
                CompletedQsoDestination.PSK_REPORTER
            )
        return results

    def _deliver(self, destination: CompletedQsoDestination) -> tuple[int, int]:
        now = _utc(self._clock())
        items = self._repository.list_due(
            destination,
            now_utc=now,
            limit=self._batch_size,
        )
        delivered = 0
        for item in items:
            try:
                if destination is CompletedQsoDestination.VOACAP:
                    assert self._voacap_sink is not None
                    self._voacap_sink.enqueue(item.event.contact)
                else:
                    assert self._psk_reporter_sink is not None
                    self._psk_reporter_sink.enqueue(item.event)
            except Exception as error:  # noqa: BLE001 - sink failures must remain isolated
                self._repository.record_failure(
                    item.event.contact.contact_id,
                    destination,
                    str(error),
                    failed_at_utc=_utc(self._clock()),
                    initial_delay=self._retry_initial_delay,
                    maximum_delay=self._retry_maximum_delay,
                )
            else:
                self._repository.mark_delivered(
                    item.event.contact.contact_id,
                    destination,
                )
                delivered += 1
        return len(items), delivered


def _columns(destination: CompletedQsoDestination) -> tuple[str, str, str, str]:
    prefix = "voacap" if destination is CompletedQsoDestination.VOACAP else "psk_reporter"
    return (
        f"{prefix}_state",
        f"{prefix}_attempt_count",
        f"{prefix}_next_attempt_at_utc",
        f"{prefix}_last_error",
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("completed-QSO producer timestamps must be timezone-aware")
    return value.astimezone(UTC)


def _time(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")


def _parse_time(value: str) -> datetime:
    return _utc(datetime.fromisoformat(value))
