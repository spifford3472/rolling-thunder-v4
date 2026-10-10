"""Durable asynchronous completed-QSO ingestion for Forge propagation work."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from json import dumps
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

from pydantic import Field, field_validator

from rolling_thunder.domain import Contact, DomainModel
from rolling_thunder.forge_propagation_history import VoacapPrediction

_INGESTION_SCHEMA_VERSION = 2
_MAX_CLAIM_LIMIT = 100
_MAX_ERROR_LENGTH = 1_000
_MAX_WORKER_IDENTITY_LENGTH = 120


class CompletedQsoIngestionError(RuntimeError):
    """Raised when the durable completed-QSO inbox cannot be used safely."""


class CompletedQsoIdempotencyConflict(CompletedQsoIngestionError):
    """Raised when a stable QSO UUID is replayed with different frozen data."""


class CompletedQsoEnqueueResult(StrEnum):
    ACCEPTED = "accepted"
    REPLAYED = "replayed"


class CompletedQsoJobState(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    RETRY = "retry"
    COMPLETED = "completed"
    DEAD_LETTER = "dead_letter"


class VoacapCorrelationDisposition(StrEnum):
    STORED = "stored"
    SKIPPED = "skipped"


class CompletedQsoLease(DomainModel):
    """One bounded worker lease over an immutable completed QSO."""

    contact: Contact
    lease_token: UUID
    worker_identity: str = Field(min_length=1, max_length=_MAX_WORKER_IDENTITY_LENGTH)
    attempt_count: int = Field(ge=1)
    leased_until_utc: datetime

    @field_validator("leased_until_utc")
    @classmethod
    def normalize_lease_time(cls, value: datetime) -> datetime:
        return _utc(value)


class CompletedQsoJobSnapshot(DomainModel):
    """Read-only state for health, tests, and future worker status publication."""

    contact: Contact
    state: CompletedQsoJobState
    attempt_count: int = Field(ge=0)
    queued_at_utc: datetime
    next_attempt_at_utc: datetime
    completed_at_utc: datetime | None = None
    last_error: str | None = None
    worker_identity: str | None = Field(
        default=None, min_length=1, max_length=_MAX_WORKER_IDENTITY_LENGTH
    )
    leased_until_utc: datetime | None = None

    @field_validator(
        "queued_at_utc", "next_attempt_at_utc", "completed_at_utc", "leased_until_utc"
    )
    @classmethod
    def normalize_snapshot_time(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _utc(value)


class CompletedQsoQueueSnapshot(DomainModel):
    """Read-only bounded-worker queue state suitable for status publication."""

    observed_at_utc: datetime
    pending_count: int = Field(ge=0)
    processing_count: int = Field(ge=0)
    retry_count: int = Field(ge=0)
    completed_count: int = Field(ge=0)
    dead_letter_count: int = Field(ge=0)
    due_count: int = Field(ge=0)
    oldest_queued_at_utc: datetime | None = None
    next_due_at_utc: datetime | None = None

    @field_validator("observed_at_utc", "oldest_queued_at_utc", "next_due_at_utc")
    @classmethod
    def normalize_queue_time(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _utc(value)


class CompletedQsoWorkResult(DomainModel):
    """One worker-cycle result with no presentation-specific semantics."""

    contact_id: UUID
    disposition: str
    error: str | None = None


class CompletedQsoCorrelator(Protocol):
    """Perform provider-facing work for one already-durable QSO snapshot."""

    def correlate(self, contact: Contact) -> VoacapCorrelationDisposition: ...


class CompletedQsoIngestionSink(Protocol):
    """Source-facing adapter contract; choosing its transport remains out of scope."""

    def enqueue(
        self, contact: Contact, *, queued_at_utc: datetime
    ) -> CompletedQsoEnqueueResult: ...


class VoacapPredictionClient(Protocol):
    def predict(self, contact: Contact) -> VoacapPrediction | None: ...


class PropagationQsoStore(Protocol):
    """Subset of propagation history persistence required by VOACAP correlation."""

    def add_qso(self, contact: Contact) -> None: ...

    def save_voacap(self, prediction: VoacapPrediction) -> None: ...


class CompletedQsoIngestionRepository:
    """Persistent inbox separating fast ingestion from provider-facing work."""

    def __init__(
        self,
        database_path: Path,
        *,
        max_attempts: int = 5,
        retry_base: timedelta = timedelta(minutes=1),
        retry_max: timedelta = timedelta(hours=1),
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if retry_base <= timedelta(0) or retry_max < retry_base:
            raise ValueError("retry durations must be positive and ordered")
        self._database_path = database_path
        self._max_attempts = max_attempts
        self._retry_base = retry_base
        self._retry_max = retry_max
        self._initialize()

    def enqueue(
        self, contact: Contact, *, queued_at_utc: datetime
    ) -> CompletedQsoEnqueueResult:
        """Durably accept one immutable contact without doing provider work."""
        queued_at = _time(_utc(queued_at_utc))
        payload = _contact_payload(contact)
        payload_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        contact_id = str(contact.contact_id)
        try:
            with sqlite3.connect(self._database_path) as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT payload_sha256, contact_json FROM completed_qso_ingestion "
                    "WHERE contact_id = ?",
                    (contact_id,),
                ).fetchone()
                if row is not None:
                    if row != (payload_hash, payload):
                        raise CompletedQsoIdempotencyConflict(
                            f"completed QSO idempotency conflict for contact_id {contact_id}"
                        )
                    connection.commit()
                    return CompletedQsoEnqueueResult.REPLAYED
                connection.execute(
                    """
                    INSERT INTO completed_qso_ingestion (
                        contact_id, payload_sha256, contact_json, state, attempt_count,
                        queued_at_utc, next_attempt_at_utc
                    ) VALUES (?, ?, ?, 'pending', 0, ?, ?)
                    """,
                    (contact_id, payload_hash, payload, queued_at, queued_at),
                )
                connection.commit()
        except CompletedQsoIngestionError:
            raise
        except sqlite3.Error as error:
            raise CompletedQsoIngestionError("completed-QSO enqueue failed") from error
        return CompletedQsoEnqueueResult.ACCEPTED

    def claim_due(
        self,
        *,
        now_utc: datetime,
        limit: int,
        lease_duration: timedelta,
        worker_identity: str,
    ) -> tuple[CompletedQsoLease, ...]:
        """Atomically lease a bounded batch, reclaiming only expired leases."""
        if not 1 <= limit <= _MAX_CLAIM_LIMIT:
            raise ValueError(f"limit must be between 1 and {_MAX_CLAIM_LIMIT}")
        if lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        identity = _worker_identity(worker_identity)
        now = _utc(now_utc)
        leased_until = now + lease_duration
        claimed_rows: list[tuple[str, str, int, str]] = []
        try:
            with sqlite3.connect(self._database_path) as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    UPDATE completed_qso_ingestion
                    SET state='dead_letter', lease_token=NULL, leased_until_utc=NULL,
                        worker_identity=NULL,
                        last_error='lease expired after final permitted attempt'
                    WHERE state='processing' AND leased_until_utc <= ?
                        AND attempt_count >= ?
                    """,
                    (_time(now), self._max_attempts),
                )
                rows = connection.execute(
                    """
                    SELECT contact_id, contact_json, attempt_count
                    FROM completed_qso_ingestion
                    WHERE ((
                        state IN ('pending', 'retry') AND next_attempt_at_utc <= ?
                    ) OR (
                        state = 'processing' AND leased_until_utc <= ?
                    )) AND attempt_count < ?
                    ORDER BY next_attempt_at_utc, queued_at_utc, contact_id
                    LIMIT ?
                    """,
                    (_time(now), _time(now), self._max_attempts, limit),
                ).fetchall()
                for contact_id, contact_json, prior_attempts in rows:
                    token = str(uuid4())
                    attempt_count = int(prior_attempts) + 1
                    connection.execute(
                        """
                        UPDATE completed_qso_ingestion
                        SET state='processing', attempt_count=?, lease_token=?,
                            leased_until_utc=?, worker_identity=?, last_error=NULL
                        WHERE contact_id=?
                        """,
                        (
                            attempt_count,
                            token,
                            _time(leased_until),
                            identity,
                            contact_id,
                        ),
                    )
                    claimed_rows.append(
                        (str(contact_id), str(contact_json), attempt_count, token)
                    )
                connection.commit()
        except sqlite3.Error as error:
            raise CompletedQsoIngestionError("completed-QSO claim failed") from error

        leases: list[CompletedQsoLease] = []
        try:
            for _contact_id, contact_json, attempt_count, token in claimed_rows:
                leases.append(
                    CompletedQsoLease(
                        contact=Contact.model_validate_json(contact_json),
                        lease_token=UUID(token),
                        worker_identity=identity,
                        attempt_count=attempt_count,
                        leased_until_utc=leased_until,
                    )
                )
        except (TypeError, ValueError) as error:
            raise CompletedQsoIngestionError(
                "stored completed-QSO payload validation failed"
            ) from error
        return tuple(leases)

    def mark_completed(
        self, lease: CompletedQsoLease, *, completed_at_utc: datetime
    ) -> None:
        """Finalize only the worker that owns the current lease token."""
        self._finish(
            lease,
            state=CompletedQsoJobState.COMPLETED,
            completed_at=_utc(completed_at_utc),
            next_attempt_at=None,
            error=None,
        )

    def mark_failed(
        self, lease: CompletedQsoLease, *, failed_at_utc: datetime, error: str
    ) -> CompletedQsoJobState:
        """Schedule bounded backoff or terminally dead-letter an exhausted job."""
        failed_at = _utc(failed_at_utc)
        terminal = lease.attempt_count >= self._max_attempts
        state = (
            CompletedQsoJobState.DEAD_LETTER if terminal else CompletedQsoJobState.RETRY
        )
        delay = min(
            self._retry_base * (2 ** (lease.attempt_count - 1)), self._retry_max
        )
        self._finish(
            lease,
            state=state,
            completed_at=None,
            next_attempt_at=None if terminal else failed_at + delay,
            error=_bounded_error_text(error),
        )
        return state

    def read(self, contact_id: UUID) -> CompletedQsoJobSnapshot | None:
        """Read one immutable job snapshot without claiming or doing provider work."""
        try:
            with sqlite3.connect(self._database_path) as connection:
                row = connection.execute(
                    """
                    SELECT contact_json, state, attempt_count, queued_at_utc,
                           next_attempt_at_utc, completed_at_utc, last_error,
                           worker_identity, leased_until_utc
                    FROM completed_qso_ingestion WHERE contact_id=?
                    """,
                    (str(contact_id),),
                ).fetchone()
        except sqlite3.Error as error:
            raise CompletedQsoIngestionError("completed-QSO read failed") from error
        if row is None:
            return None
        try:
            return CompletedQsoJobSnapshot(
                contact=Contact.model_validate_json(row[0]),
                state=row[1],
                attempt_count=row[2],
                queued_at_utc=row[3],
                next_attempt_at_utc=row[4],
                completed_at_utc=row[5],
                last_error=row[6],
                worker_identity=row[7],
                leased_until_utc=row[8],
            )
        except (TypeError, ValueError) as error:
            raise CompletedQsoIngestionError(
                "stored completed-QSO state validation failed"
            ) from error

    def observe(self, *, now_utc: datetime) -> CompletedQsoQueueSnapshot:
        """Return queue counts and timing without claiming work or calling providers."""
        now = _utc(now_utc)
        try:
            with sqlite3.connect(self._database_path) as connection:
                rows = connection.execute(
                    """
                    SELECT state, COUNT(*)
                    FROM completed_qso_ingestion
                    GROUP BY state
                    """
                ).fetchall()
                timing = connection.execute(
                    """
                    SELECT
                        SUM(CASE WHEN (
                            state IN ('pending', 'retry') AND next_attempt_at_utc <= ?
                        ) OR (
                            state = 'processing' AND leased_until_utc <= ?
                        ) THEN 1 ELSE 0 END),
                        MIN(CASE WHEN state IN ('pending', 'retry', 'processing')
                            THEN queued_at_utc END),
                        MIN(CASE
                            WHEN state IN ('pending', 'retry') THEN next_attempt_at_utc
                            WHEN state = 'processing' THEN leased_until_utc
                        END)
                    FROM completed_qso_ingestion
                    """,
                    (_time(now), _time(now)),
                ).fetchone()
        except sqlite3.Error as error:
            raise CompletedQsoIngestionError("completed-QSO observation failed") from error
        counts = {CompletedQsoJobState(state): int(count) for state, count in rows}
        due_count, oldest_queued, next_due = timing or (0, None, None)
        return CompletedQsoQueueSnapshot(
            observed_at_utc=now,
            pending_count=counts.get(CompletedQsoJobState.PENDING, 0),
            processing_count=counts.get(CompletedQsoJobState.PROCESSING, 0),
            retry_count=counts.get(CompletedQsoJobState.RETRY, 0),
            completed_count=counts.get(CompletedQsoJobState.COMPLETED, 0),
            dead_letter_count=counts.get(CompletedQsoJobState.DEAD_LETTER, 0),
            due_count=int(due_count or 0),
            oldest_queued_at_utc=oldest_queued,
            next_due_at_utc=next_due,
        )

    def _finish(
        self,
        lease: CompletedQsoLease,
        *,
        state: CompletedQsoJobState,
        completed_at: datetime | None,
        next_attempt_at: datetime | None,
        error: str | None,
    ) -> None:
        try:
            with sqlite3.connect(self._database_path) as connection:
                cursor = connection.execute(
                    """
                    UPDATE completed_qso_ingestion
                    SET state=?, lease_token=NULL, leased_until_utc=NULL,
                        worker_identity=NULL,
                        completed_at_utc=?, next_attempt_at_utc=COALESCE(?, next_attempt_at_utc),
                        last_error=?
                    WHERE contact_id=? AND state='processing' AND lease_token=?
                        AND worker_identity=?
                    """,
                    (
                        state.value,
                        None if completed_at is None else _time(completed_at),
                        None if next_attempt_at is None else _time(next_attempt_at),
                        error,
                        str(lease.contact.contact_id),
                        str(lease.lease_token),
                        lease.worker_identity,
                    ),
                )
                if cursor.rowcount != 1:
                    raise CompletedQsoIngestionError(
                        "completed-QSO lease is stale or no longer processing"
                    )
                connection.commit()
        except CompletedQsoIngestionError:
            raise
        except sqlite3.Error as sqlite_error:
            raise CompletedQsoIngestionError("completed-QSO finalization failed") from sqlite_error

    def _initialize(self) -> None:
        try:
            self._database_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self._database_path) as connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS qso_ingestion_schema_metadata (
                        singleton_id INTEGER PRIMARY KEY CHECK(singleton_id=1),
                        schema_version INTEGER NOT NULL
                    );
                    INSERT OR IGNORE INTO qso_ingestion_schema_metadata VALUES (1, 2);
                    CREATE TABLE IF NOT EXISTS completed_qso_ingestion (
                        contact_id TEXT PRIMARY KEY,
                        payload_sha256 TEXT NOT NULL,
                        contact_json TEXT NOT NULL,
                        state TEXT NOT NULL CHECK(state IN (
                            'pending', 'processing', 'retry', 'completed', 'dead_letter'
                        )),
                        attempt_count INTEGER NOT NULL CHECK(attempt_count >= 0),
                        queued_at_utc TEXT NOT NULL,
                        next_attempt_at_utc TEXT NOT NULL,
                        lease_token TEXT,
                        leased_until_utc TEXT,
                        worker_identity TEXT,
                        completed_at_utc TEXT,
                        last_error TEXT
                    );
                    CREATE INDEX IF NOT EXISTS completed_qso_ingestion_due
                    ON completed_qso_ingestion(state, next_attempt_at_utc);
                    """
                )
                version = connection.execute(
                    "SELECT schema_version FROM qso_ingestion_schema_metadata "
                    "WHERE singleton_id=1"
                ).fetchone()
                if version == (1,):
                    connection.execute(
                        "ALTER TABLE completed_qso_ingestion ADD COLUMN worker_identity TEXT"
                    )
                    connection.execute(
                        "UPDATE qso_ingestion_schema_metadata SET schema_version=2 "
                        "WHERE singleton_id=1"
                    )
                    version = (2,)
                if version != (_INGESTION_SCHEMA_VERSION,):
                    raise CompletedQsoIngestionError(
                        "unsupported completed-QSO ingestion schema version"
                    )
                connection.commit()
        except CompletedQsoIngestionError:
            raise
        except (OSError, sqlite3.Error) as error:
            raise CompletedQsoIngestionError(
                "completed-QSO ingestion initialization failed"
            ) from error


class VoacapCompletedQsoCorrelator:
    """Archive a frozen QSO, then capture one versioned VOACAP prediction."""

    def __init__(
        self, history: PropagationQsoStore, client: VoacapPredictionClient
    ) -> None:
        self._history = history
        self._client = client

    def correlate(self, contact: Contact) -> VoacapCorrelationDisposition:
        self._history.add_qso(contact)
        prediction = self._client.predict(contact)
        if prediction is None:
            return VoacapCorrelationDisposition.SKIPPED
        if prediction.contact_id != contact.contact_id:
            raise ValueError("VOACAP prediction contact_id does not match completed QSO")
        self._history.save_voacap(prediction)
        return VoacapCorrelationDisposition.STORED


class CompletedQsoCorrelationWorker:
    """Run a bounded due batch; each QSO failure is isolated and retryable."""

    def __init__(
        self,
        repository: CompletedQsoIngestionRepository,
        correlator: CompletedQsoCorrelator,
        *,
        worker_identity: str,
        batch_limit: int = 20,
        lease_duration: timedelta = timedelta(minutes=5),
    ) -> None:
        if not 1 <= batch_limit <= _MAX_CLAIM_LIMIT:
            raise ValueError(f"batch_limit must be between 1 and {_MAX_CLAIM_LIMIT}")
        if lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        self._repository = repository
        self._correlator = correlator
        self._worker_identity = _worker_identity(worker_identity)
        self._batch_limit = batch_limit
        self._lease_duration = lease_duration

    def run_due(self, *, now_utc: datetime) -> tuple[CompletedQsoWorkResult, ...]:
        """Process at most ``batch_limit`` jobs; a scheduler may call this later."""
        now = _utc(now_utc)
        leases = self._repository.claim_due(
            now_utc=now,
            limit=self._batch_limit,
            lease_duration=self._lease_duration,
            worker_identity=self._worker_identity,
        )
        results: list[CompletedQsoWorkResult] = []
        for lease in leases:
            try:
                disposition = self._correlator.correlate(lease.contact)
            except Exception as error:  # noqa: BLE001 - jobs are deliberately isolated
                message = _bounded_error(error)
                try:
                    state = self._repository.mark_failed(
                        lease, failed_at_utc=now, error=message
                    )
                except CompletedQsoIngestionError as persistence_error:
                    results.append(
                        CompletedQsoWorkResult(
                            contact_id=lease.contact.contact_id,
                            disposition="lease_error",
                            error=_bounded_error(persistence_error),
                        )
                    )
                else:
                    results.append(
                        CompletedQsoWorkResult(
                            contact_id=lease.contact.contact_id,
                            disposition=state.value,
                            error=message,
                        )
                    )
                continue
            try:
                self._repository.mark_completed(lease, completed_at_utc=now)
            except CompletedQsoIngestionError as error:
                results.append(
                    CompletedQsoWorkResult(
                        contact_id=lease.contact.contact_id,
                        disposition="lease_error",
                        error=_bounded_error(error),
                    )
                )
            else:
                results.append(
                    CompletedQsoWorkResult(
                        contact_id=lease.contact.contact_id,
                        disposition=disposition.value,
                    )
                )
        return tuple(results)


def _contact_payload(contact: Contact) -> str:
    return dumps(contact.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _time(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")


def _bounded_error(error: BaseException) -> str:
    return _bounded_error_text(str(error) or error.__class__.__name__)


def _bounded_error_text(error: str) -> str:
    return (error.strip() or "unknown error")[:_MAX_ERROR_LENGTH]


def _worker_identity(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("worker_identity must not be blank")
    if len(normalized) > _MAX_WORKER_IDENTITY_LENGTH:
        raise ValueError(
            f"worker_identity must not exceed {_MAX_WORKER_IDENTITY_LENGTH} characters"
        )
    return normalized
