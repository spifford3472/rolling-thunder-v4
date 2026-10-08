"""Durable, production-inactive orchestration for completed FT8 PSK analytics."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from json import dumps
from math import ceil
from pathlib import Path
from typing import Protocol
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from rolling_thunder.domain import Contact, ContactSource, DomainModel, RadioMode
from rolling_thunder.forge_propagation_history import (
    ForgePropagationHistoryRepository,
    PskReporterCollectionStatus,
    PskReporterSummary,
)
from rolling_thunder.forge_pskreporter import (
    PskReporterAnalyticsService,
    PskReporterConfig,
    PskReporterHttpClient,
    build_pskreporter_query_parameters,
)
from rolling_thunder.ft8.performance import FT8AttemptOutcome, FT8PerformanceAttempt

_SCHEMA_VERSION = 1
_MAX_PROVIDER_WINDOW_S = 86_400
_FREQUENCY_TOLERANCE_HZ = 10_000
_TERMINAL_STATUSES = {
    PskReporterCollectionStatus.QUERIED_ZERO_REPORTS,
    PskReporterCollectionStatus.QUERIED_WITH_REPORTS,
}


class PskReporterOrchestrationError(RuntimeError):
    """Raised when durable PSK orchestration state cannot be used safely."""


class CompletedFt8EventConflict(PskReporterOrchestrationError):
    """Raised when one QSO UUID is replayed with changed immutable data."""


class CompletedFt8EventDisposition(StrEnum):
    ACCEPTED = "accepted"
    REPLAYED = "replayed"


class PskReporterEventState(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    EXPIRED = "expired"


class PskReporterWindowState(StrEnum):
    RESERVED = "reserved"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class PskReporterWorkerDisposition(StrEnum):
    DISABLED = "disabled"
    IDLE = "idle"
    PACED = "paced"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class CompletedFt8QsoEvent(DomainModel):
    """Confirmed durable contact plus its matching successful terminal attempt."""

    schema_version: int = Field(default=1, ge=1, le=1)
    contact: Contact
    terminal_attempt: FT8PerformanceAttempt

    @model_validator(mode="after")
    def validate_confirmation(self) -> CompletedFt8QsoEvent:
        attempt = self.terminal_attempt
        contact = self.contact
        if contact.source is not ContactSource.FT8 or contact.mode is not RadioMode.FT8:
            raise ValueError("completed event contact must be an FT8 contact")
        if attempt.outcome is not FT8AttemptOutcome.COMPLETED or not attempt.success:
            raise ValueError("completed event requires a successful terminal FT8 attempt")
        if attempt.attempt_id != contact.contact_id:
            raise ValueError("terminal attempt UUID must match the contact UUID")
        if str(attempt.callsign) != str(contact.callsign):
            raise ValueError("terminal attempt callsign must match the contact")
        if attempt.started_at_utc != contact.started_at:
            raise ValueError("terminal attempt start must match the contact start")
        if (
            attempt.dial_frequency_hz is not None
            and attempt.dial_frequency_hz != contact.frequency_hz
        ):
            raise ValueError("terminal attempt frequency must match the contact")
        return self


class CompletedFt8QsoEventSink(Protocol):
    """Authorized ingestion boundary; transport/authentication belong to its owner."""

    def enqueue(
        self, event: CompletedFt8QsoEvent, *, received_at_utc: datetime
    ) -> CompletedFt8EventDisposition: ...


class PskReporterRequestWindow(DomainModel):
    """Exact absolute request window reserved before any provider I/O."""

    window_key: str = Field(min_length=64, max_length=64)
    window_start_utc: datetime
    window_end_utc: datetime
    query_parameters: dict[str, str | int]
    events: tuple[CompletedFt8QsoEvent, ...]

    @field_validator("window_start_utc", "window_end_utc")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return _utc(value)


class PskReporterOrchestrationHealth(DomainModel):
    """Provider-I/O-free durable status for supervision and diagnostics."""

    observed_at_utc: datetime
    enabled: bool
    pending_count: int = Field(ge=0)
    due_count: int = Field(ge=0)
    completed_count: int = Field(ge=0)
    expired_count: int = Field(ge=0)
    last_provider_attempt_at_utc: datetime | None = None
    next_provider_attempt_at_utc: datetime | None = None
    last_window_state: PskReporterWindowState | None = None
    last_error: str | None = None

    @field_validator(
        "observed_at_utc",
        "last_provider_attempt_at_utc",
        "next_provider_attempt_at_utc",
    )
    @classmethod
    def normalize_health_time(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _utc(value)


class PskReporterWorkerResult(DomainModel):
    disposition: PskReporterWorkerDisposition
    window_key: str | None = None
    contact_ids: tuple[UUID, ...] = ()
    outcomes: tuple[PskReporterSummary, ...] = ()
    error: str | None = None


class PskReporterSummaryStore(Protocol):
    """History subset used to reconcile provider results after worker restart."""

    def read_pskreporter(self, contact_id: UUID) -> PskReporterSummary | None: ...


class PskReporterOrchestrationRepository:
    """Own exact event replay, request-window idempotence, and global pacing."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._initialize()

    def enqueue(
        self,
        event: CompletedFt8QsoEvent,
        *,
        received_at_utc: datetime,
        report_latency: timedelta,
    ) -> CompletedFt8EventDisposition:
        if report_latency < timedelta(minutes=5):
            raise ValueError("PSK Reporter latency must be at least five minutes")
        received_at = _utc(received_at_utc)
        eligible_at = event.terminal_attempt.ended_at_utc + report_latency
        payload = event.model_dump_json()
        payload_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        contact_id = str(event.contact.contact_id)
        try:
            with sqlite3.connect(self._database_path) as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT payload_sha256, event_json, eligible_at_utc "
                    "FROM pskreporter_completed_ft8_event WHERE contact_id=?",
                    (contact_id,),
                ).fetchone()
                expected = (payload_hash, payload, _time(eligible_at))
                if row is not None:
                    if row != expected:
                        raise CompletedFt8EventConflict(
                            f"completed FT8 event conflict for contact_id {contact_id}"
                        )
                    connection.commit()
                    return CompletedFt8EventDisposition.REPLAYED
                connection.execute(
                    """
                    INSERT INTO pskreporter_completed_ft8_event (
                        contact_id, payload_sha256, event_json, received_at_utc,
                        eligible_at_utc, state
                    ) VALUES (?, ?, ?, ?, ?, 'pending')
                    """,
                    (
                        contact_id,
                        payload_hash,
                        payload,
                        _time(received_at),
                        _time(eligible_at),
                    ),
                )
                connection.commit()
        except CompletedFt8EventConflict:
            raise
        except sqlite3.Error as error:
            raise PskReporterOrchestrationError("completed FT8 event enqueue failed") from error
        return CompletedFt8EventDisposition.ACCEPTED

    def reconcile_terminal(self, summaries: PskReporterSummaryStore) -> int:
        """Finalize events already durably completed by the analytics repository."""
        pending = self._pending_events()
        completed_ids = [
            event.contact.contact_id
            for event in pending
            if (summary := summaries.read_pskreporter(event.contact.contact_id)) is not None
            and summary.status in _TERMINAL_STATUSES
        ]
        if not completed_ids:
            return 0
        try:
            with sqlite3.connect(self._database_path) as connection:
                connection.executemany(
                    "UPDATE pskreporter_completed_ft8_event SET state='completed', "
                    "last_error=NULL WHERE contact_id=? AND state='pending'",
                    ((str(contact_id),) for contact_id in completed_ids),
                )
                connection.commit()
        except sqlite3.Error as error:
            raise PskReporterOrchestrationError("terminal event reconciliation failed") from error
        return len(completed_ids)

    def reserve_due_window(
        self, *, now_utc: datetime, config: PskReporterConfig
    ) -> PskReporterRequestWindow | None:
        """Atomically reserve one bounded batch and the process-global provider slot."""
        now = _utc(now_utc)
        try:
            with sqlite3.connect(self._database_path) as connection:
                connection.execute("BEGIN IMMEDIATE")
                gate = connection.execute(
                    "SELECT last_attempt_at_utc FROM pskreporter_provider_gate "
                    "WHERE singleton_id=1"
                ).fetchone()
                if gate is not None and gate[0] is not None:
                    last_attempt = _parse_time(str(gate[0]))
                    if now - last_attempt < config.minimum_query_interval:
                        connection.commit()
                        return None
                rows = connection.execute(
                    """
                    SELECT event_json FROM pskreporter_completed_ft8_event
                    WHERE state='pending' AND eligible_at_utc <= ?
                    ORDER BY eligible_at_utc, received_at_utc, contact_id
                    LIMIT ?
                    """,
                    (_time(now), config.maximum_qsos_per_query),
                ).fetchall()
                if not rows:
                    connection.commit()
                    return None
                events = tuple(CompletedFt8QsoEvent.model_validate_json(row[0]) for row in rows)
                oldest = min(event.contact.started_at for event in events)
                window_s = max(
                    config.recent_window_s,
                    ceil((now - oldest).total_seconds()) + config.correlation_window_s,
                )
                if window_s > _MAX_PROVIDER_WINDOW_S:
                    expired = tuple(
                        event
                        for event in events
                        if ceil((now - event.contact.started_at).total_seconds())
                        + config.correlation_window_s
                        > _MAX_PROVIDER_WINDOW_S
                    )
                    connection.executemany(
                        "UPDATE pskreporter_completed_ft8_event SET state='expired', "
                        "last_error=? WHERE contact_id=?",
                        (
                            (
                                "QSO is outside PSK Reporter's 24-hour retrieval window",
                                str(event.contact.contact_id),
                            )
                            for event in expired
                        ),
                    )
                    connection.commit()
                    return None
                frequency_range = _frequency_range(events)
                parameters = build_pskreporter_query_parameters(
                    config,
                    window_s=window_s,
                    frequency_range_hz=frequency_range,
                )
                window_start = now - timedelta(seconds=window_s)
                contact_ids = tuple(str(event.contact.contact_id) for event in events)
                identity = {
                    "window_start_utc": _time(window_start),
                    "window_end_utc": _time(now),
                    "query_parameters": parameters,
                    "contact_ids": contact_ids,
                }
                identity_json = _json(identity)
                window_key = hashlib.sha256(identity_json.encode("utf-8")).hexdigest()
                connection.execute(
                    """
                    INSERT INTO pskreporter_request_window (
                        window_key, window_start_utc, window_end_utc,
                        query_parameters_json, contact_ids_json, state, reserved_at_utc
                    ) VALUES (?, ?, ?, ?, ?, 'reserved', ?)
                    """,
                    (
                        window_key,
                        _time(window_start),
                        _time(now),
                        _json(parameters),
                        _json(contact_ids),
                        _time(now),
                    ),
                )
                connection.execute(
                    "UPDATE pskreporter_provider_gate SET last_attempt_at_utc=? "
                    "WHERE singleton_id=1",
                    (_time(now),),
                )
                connection.commit()
        except (TypeError, ValueError) as error:
            raise PskReporterOrchestrationError(
                "stored completed FT8 event validation failed"
            ) from error
        except sqlite3.IntegrityError as error:
            raise PskReporterOrchestrationError(
                "exact PSK Reporter request window was already reserved"
            ) from error
        except sqlite3.Error as error:
            raise PskReporterOrchestrationError("request-window reservation failed") from error
        return PskReporterRequestWindow(
            window_key=window_key,
            window_start_utc=window_start,
            window_end_utc=now,
            query_parameters=parameters,
            events=events,
        )

    def finish_window(
        self,
        window: PskReporterRequestWindow,
        outcomes: tuple[PskReporterSummary, ...],
    ) -> None:
        by_id = {outcome.contact_id: outcome for outcome in outcomes}
        expected_ids = {event.contact.contact_id for event in window.events}
        if set(by_id) != expected_ids:
            raise ValueError("window outcomes must exactly match reserved contacts")
        succeeded = all(outcome.status in _TERMINAL_STATUSES for outcome in outcomes)
        errors = tuple(outcome.last_error for outcome in outcomes if outcome.last_error)
        error = None if succeeded else (errors[0] if errors else "PSK Reporter query not completed")
        try:
            with sqlite3.connect(self._database_path) as connection:
                connection.execute("BEGIN IMMEDIATE")
                cursor = connection.execute(
                    """
                    UPDATE pskreporter_request_window
                    SET state=?, completed_at_utc=?, last_error=?
                    WHERE window_key=? AND state='reserved'
                    """,
                    (
                        (
                            PskReporterWindowState.SUCCEEDED.value
                            if succeeded
                            else PskReporterWindowState.FAILED.value
                        ),
                        _time(window.window_end_utc),
                        error,
                        window.window_key,
                    ),
                )
                if cursor.rowcount != 1:
                    raise PskReporterOrchestrationError(
                        "request window is stale or already finalized"
                    )
                for event in window.events:
                    outcome = by_id[event.contact.contact_id]
                    connection.execute(
                        """
                        UPDATE pskreporter_completed_ft8_event
                        SET state=?, last_error=?, last_window_key=?
                        WHERE contact_id=? AND state='pending'
                        """,
                        (
                            (
                                PskReporterEventState.COMPLETED.value
                                if outcome.status in _TERMINAL_STATUSES
                                else PskReporterEventState.PENDING.value
                            ),
                            outcome.last_error,
                            window.window_key,
                            str(event.contact.contact_id),
                        ),
                    )
                connection.commit()
        except PskReporterOrchestrationError:
            raise
        except sqlite3.Error as sql_error:
            raise PskReporterOrchestrationError("request-window finalization failed") from sql_error

    def health(
        self, *, now_utc: datetime, enabled: bool, minimum_interval: timedelta
    ) -> PskReporterOrchestrationHealth:
        now = _utc(now_utc)
        try:
            with sqlite3.connect(self._database_path) as connection:
                counts = dict(
                    connection.execute(
                        "SELECT state, COUNT(*) FROM pskreporter_completed_ft8_event "
                        "GROUP BY state"
                    ).fetchall()
                )
                due = connection.execute(
                    "SELECT COUNT(*) FROM pskreporter_completed_ft8_event "
                    "WHERE state='pending' AND eligible_at_utc <= ?",
                    (_time(now),),
                ).fetchone()
                gate = connection.execute(
                    "SELECT last_attempt_at_utc FROM pskreporter_provider_gate "
                    "WHERE singleton_id=1"
                ).fetchone()
                latest = connection.execute(
                    "SELECT state, last_error FROM pskreporter_request_window "
                    "ORDER BY reserved_at_utc DESC, window_key DESC LIMIT 1"
                ).fetchone()
        except sqlite3.Error as error:
            raise PskReporterOrchestrationError("PSK orchestration health read failed") from error
        last_attempt = None if gate is None or gate[0] is None else _parse_time(str(gate[0]))
        return PskReporterOrchestrationHealth(
            observed_at_utc=now,
            enabled=enabled,
            pending_count=int(counts.get(PskReporterEventState.PENDING.value, 0)),
            due_count=0 if due is None else int(due[0]),
            completed_count=int(counts.get(PskReporterEventState.COMPLETED.value, 0)),
            expired_count=int(counts.get(PskReporterEventState.EXPIRED.value, 0)),
            last_provider_attempt_at_utc=last_attempt,
            next_provider_attempt_at_utc=(
                None if last_attempt is None else last_attempt + minimum_interval
            ),
            last_window_state=None if latest is None else latest[0],
            last_error=None if latest is None else latest[1],
        )

    def _pending_events(self) -> tuple[CompletedFt8QsoEvent, ...]:
        try:
            with sqlite3.connect(self._database_path) as connection:
                rows = connection.execute(
                    "SELECT event_json FROM pskreporter_completed_ft8_event "
                    "WHERE state='pending' ORDER BY received_at_utc, contact_id"
                ).fetchall()
        except sqlite3.Error as error:
            raise PskReporterOrchestrationError("pending event read failed") from error
        try:
            return tuple(CompletedFt8QsoEvent.model_validate_json(row[0]) for row in rows)
        except (TypeError, ValueError) as error:
            raise PskReporterOrchestrationError(
                "stored completed FT8 event validation failed"
            ) from error

    def _initialize(self) -> None:
        try:
            self._database_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self._database_path) as connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS pskreporter_orchestration_schema (
                        singleton_id INTEGER PRIMARY KEY CHECK(singleton_id=1),
                        schema_version INTEGER NOT NULL
                    );
                    INSERT OR IGNORE INTO pskreporter_orchestration_schema VALUES (1, 1);
                    CREATE TABLE IF NOT EXISTS pskreporter_completed_ft8_event (
                        contact_id TEXT PRIMARY KEY,
                        payload_sha256 TEXT NOT NULL,
                        event_json TEXT NOT NULL,
                        received_at_utc TEXT NOT NULL,
                        eligible_at_utc TEXT NOT NULL,
                        state TEXT NOT NULL CHECK(state IN ('pending', 'completed', 'expired')),
                        last_window_key TEXT,
                        last_error TEXT
                    );
                    CREATE INDEX IF NOT EXISTS pskreporter_completed_ft8_due
                    ON pskreporter_completed_ft8_event(state, eligible_at_utc);
                    CREATE TABLE IF NOT EXISTS pskreporter_request_window (
                        window_key TEXT PRIMARY KEY,
                        window_start_utc TEXT NOT NULL,
                        window_end_utc TEXT NOT NULL,
                        query_parameters_json TEXT NOT NULL,
                        contact_ids_json TEXT NOT NULL,
                        state TEXT NOT NULL CHECK(state IN ('reserved', 'succeeded', 'failed')),
                        reserved_at_utc TEXT NOT NULL,
                        completed_at_utc TEXT,
                        last_error TEXT
                    );
                    CREATE TABLE IF NOT EXISTS pskreporter_provider_gate (
                        singleton_id INTEGER PRIMARY KEY CHECK(singleton_id=1),
                        last_attempt_at_utc TEXT
                    );
                    INSERT OR IGNORE INTO pskreporter_provider_gate VALUES (1, NULL);
                    """
                )
                version = connection.execute(
                    "SELECT schema_version FROM pskreporter_orchestration_schema "
                    "WHERE singleton_id=1"
                ).fetchone()
                if version != (_SCHEMA_VERSION,):
                    raise PskReporterOrchestrationError(
                        "unsupported PSK Reporter orchestration schema version"
                    )
                connection.commit()
        except PskReporterOrchestrationError:
            raise
        except (OSError, sqlite3.Error) as error:
            raise PskReporterOrchestrationError(
                "PSK Reporter orchestration initialization failed"
            ) from error


class PskReporterCompletedEventAdapter:
    """Narrow sink for an authenticated QSO source; it owns no source authority."""

    def __init__(
        self,
        repository: PskReporterOrchestrationRepository,
        config: PskReporterConfig,
    ) -> None:
        self._repository = repository
        self._config = config

    def enqueue(
        self, event: CompletedFt8QsoEvent, *, received_at_utc: datetime
    ) -> CompletedFt8EventDisposition:
        return self._repository.enqueue(
            event,
            received_at_utc=received_at_utc,
            report_latency=timedelta(seconds=self._config.report_latency_s),
        )


class _EventCompletionTimes:
    def __init__(self, events: tuple[CompletedFt8QsoEvent, ...]) -> None:
        self._values = {
            event.contact.contact_id: event.terminal_attempt.ended_at_utc for event in events
        }

    def ended_at_utc(self, contact_id: UUID) -> datetime | None:
        return self._values.get(contact_id)


class PskReporterOrchestrationWorker:
    """Run one bounded due window outside FT8 and contact-sync execution paths."""

    def __init__(
        self,
        repository: PskReporterOrchestrationRepository,
        history: ForgePropagationHistoryRepository,
        config: PskReporterConfig,
        *,
        client: PskReporterHttpClient | None = None,
    ) -> None:
        self._repository = repository
        self._history = history
        self._config = config
        self._client = client or PskReporterHttpClient(config)

    def run_once(self, *, now_utc: datetime) -> PskReporterWorkerResult:
        now = _utc(now_utc)
        if not self._config.enabled:
            return PskReporterWorkerResult(
                disposition=PskReporterWorkerDisposition.DISABLED
            )
        self._repository.reconcile_terminal(self._history)
        health = self._repository.health(
            now_utc=now,
            enabled=True,
            minimum_interval=self._config.minimum_query_interval,
        )
        window = self._repository.reserve_due_window(now_utc=now, config=self._config)
        if window is None:
            disposition = (
                PskReporterWorkerDisposition.PACED
                if health.due_count > 0
                and health.next_provider_attempt_at_utc is not None
                and now < health.next_provider_attempt_at_utc
                else PskReporterWorkerDisposition.IDLE
            )
            return PskReporterWorkerResult(disposition=disposition)
        service = PskReporterAnalyticsService(
            self._history,
            self._config,
            client=self._client,
            completion_time_provider=_EventCompletionTimes(window.events),
        )
        outcomes = service.collect_recent(
            tuple(event.contact for event in window.events), now=window.window_end_utc
        )
        self._repository.finish_window(window, outcomes)
        succeeded = all(outcome.status in _TERMINAL_STATUSES for outcome in outcomes)
        error = next((outcome.last_error for outcome in outcomes if outcome.last_error), None)
        return PskReporterWorkerResult(
            disposition=(
                PskReporterWorkerDisposition.SUCCEEDED
                if succeeded
                else PskReporterWorkerDisposition.FAILED
            ),
            window_key=window.window_key,
            contact_ids=tuple(event.contact.contact_id for event in window.events),
            outcomes=outcomes,
            error=error,
        )


def _frequency_range(
    events: tuple[CompletedFt8QsoEvent, ...],
) -> tuple[int, int] | None:
    if not events:
        return None
    frequencies = [event.contact.frequency_hz for event in events]
    return (
        max(1, min(frequencies) - _FREQUENCY_TOLERANCE_HZ),
        max(frequencies) + _FREQUENCY_TOLERANCE_HZ,
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _time(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def _json(value: object) -> str:
    return dumps(value, sort_keys=True, separators=(",", ":"))
