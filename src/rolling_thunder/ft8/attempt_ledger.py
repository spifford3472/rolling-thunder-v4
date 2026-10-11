"""Durable, provider-neutral FT8 terminal-attempt event ledger.

The ledger is deliberately separate from contacts and Wavelog.  It snapshots the
existing terminal-performance and transmit-period owners, then offers bounded,
restart-safe store-forward delivery without performing network work at capture.
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from json import dumps
from pathlib import Path
from typing import Literal, Protocol
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from rolling_thunder.domain import DomainModel
from rolling_thunder.ft8.hardware_transmit import FT8TransmitPeriodTelemetry
from rolling_thunder.ft8.performance import FT8AttemptOutcome, FT8PerformanceAttempt
from rolling_thunder.radio_polling import PollScheduler, ScheduledPoll

ATTEMPT_EVENT_SCHEMA_VERSION = 1
_MAX_BATCH = 100
_MAX_ERROR = 1_000
_LOGGER = logging.getLogger("rolling_thunder.ft8.attempt_ledger")


class FT8AttemptClassification(StrEnum):
    """Analysis-safe terminal categories; missing evidence is never a failure."""

    SUCCESS = "success"
    NO_ANSWER = "no_answer"
    ABORT = "abort"
    BUSY = "busy"
    INTERRUPTION = "interruption"
    FAULT = "fault"


class FT8ReportDirection(StrEnum):
    LOCAL_REPORT_OF_REMOTE = "local_report_of_remote"
    REMOTE_REPORT_OF_LOCAL = "remote_report_of_local"


class FT8AttemptReport(DomainModel):
    direction: FT8ReportDirection
    value_db: int = Field(ge=-50, le=49)
    unit: Literal["ft8_decoder_db"] = "ft8_decoder_db"


class FT8AttemptTxPeriod(DomainModel):
    sequence: int = Field(ge=1)
    started_at_utc: datetime
    ended_at_utc: datetime
    configured_power_watts: int | None = Field(default=None, ge=5, le=100)
    power_source: Literal["cat_configured_readback"] | None = None
    frequency_hz: int = Field(gt=0)
    transmitted: bool
    transmit_audio_offset_hz: int | None = Field(default=None, ge=200, le=3500)

    @field_validator("started_at_utc", "ended_at_utc")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def validate_period(self) -> FT8AttemptTxPeriod:
        if self.ended_at_utc < self.started_at_utc:
            raise ValueError("transmit period end cannot precede start")
        if (self.configured_power_watts is None) != (self.power_source is None):
            raise ValueError("configured power and provenance must be present together")
        return self


class FT8AttemptEvent(DomainModel):
    """Complete immutable source event for one terminal FT8 attempt."""

    schema_version: Literal[1] = 1
    attempt_uuid: UUID
    contact_uuid: UUID | None = None
    source_event_created_utc: datetime
    started_at_utc: datetime
    ended_at_utc: datetime
    classification: FT8AttemptClassification
    source_outcome: FT8AttemptOutcome
    terminal_phase: str = Field(min_length=1, max_length=64)
    terminal_reason: str | None = Field(default=None, max_length=1000)
    remote_callsign: str = Field(min_length=1, max_length=20)
    band: str | None = Field(default=None, max_length=16)
    dial_frequency_hz: int | None = Field(default=None, gt=0)
    mode: Literal["FT8"] = "FT8"
    local_grid: str | None = Field(default=None, min_length=4, max_length=6)
    local_latitude: float | None = Field(default=None, ge=-90, le=90)
    local_longitude: float | None = Field(default=None, ge=-180, le=180)
    remote_grid: str | None = Field(default=None, min_length=4, max_length=6)
    remote_grid_source: Literal["decoded_ft8"] | None = None
    reports: tuple[FT8AttemptReport, ...] = Field(default=(), max_length=2)
    tx_periods: tuple[FT8AttemptTxPeriod, ...] = Field(default=(), max_length=64)
    initial_configured_power_watts: int | None = Field(default=None, ge=5, le=100)
    final_configured_power_watts: int | None = Field(default=None, ge=5, le=100)
    maximum_configured_power_watts: int | None = Field(default=None, ge=5, le=100)
    transmit_attempt_count: int = Field(ge=0)
    busy_extension_attempts: int = Field(ge=0, le=2)

    @field_validator("source_event_created_utc", "started_at_utc", "ended_at_utc")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def validate_event(self) -> FT8AttemptEvent:
        if self.ended_at_utc < self.started_at_utc:
            raise ValueError("attempt end cannot precede start")
        if (self.local_latitude is None) != (self.local_longitude is None):
            raise ValueError("local latitude and longitude must be present together")
        if (self.remote_grid is None) != (self.remote_grid_source is None):
            raise ValueError("remote grid and provenance must be present together")
        if self.contact_uuid is not None:
            if self.classification is not FT8AttemptClassification.SUCCESS:
                raise ValueError("only a successful attempt may reference a contact")
            if self.contact_uuid != self.attempt_uuid:
                raise ValueError("FT8 contact and attempt UUIDs must match")
        sequences = tuple(period.sequence for period in self.tx_periods)
        if sequences != tuple(range(1, len(sequences) + 1)):
            raise ValueError("transmit period sequences must be contiguous from one")
        return self

    @property
    def payload_sha256(self) -> str:
        return hashlib.sha256(_payload(self).encode()).hexdigest()


def build_attempt_event(
    attempt: FT8PerformanceAttempt,
    periods: tuple[FT8TransmitPeriodTelemetry, ...],
    *,
    created_at_utc: datetime,
    contact_is_durable: bool = False,
) -> FT8AttemptEvent:
    """Snapshot existing owners after terminal durability, without provider work."""
    reports: list[FT8AttemptReport] = []
    if attempt.sent_report_db is not None:
        reports.append(
            FT8AttemptReport(
                direction=FT8ReportDirection.LOCAL_REPORT_OF_REMOTE,
                value_db=attempt.sent_report_db,
            )
        )
    if attempt.received_report_db is not None:
        reports.append(
            FT8AttemptReport(
                direction=FT8ReportDirection.REMOTE_REPORT_OF_LOCAL,
                value_db=attempt.received_report_db,
            )
        )
    tx_periods = tuple(
        FT8AttemptTxPeriod(
            sequence=index,
            started_at_utc=period.started_at_utc,
            ended_at_utc=period.ended_at_utc,
            configured_power_watts=period.configured_power_watts,
            power_source=(
                "cat_configured_readback" if period.power_readback_verified else None
            ),
            frequency_hz=period.frequency_hz,
            transmitted=period.transmitted,
            transmit_audio_offset_hz=period.transmit_audio_offset_hz,
        )
        for index, period in enumerate(periods, start=1)
    )
    return FT8AttemptEvent(
        attempt_uuid=attempt.attempt_id,
        contact_uuid=attempt.attempt_id if contact_is_durable else None,
        source_event_created_utc=created_at_utc,
        started_at_utc=attempt.started_at_utc,
        ended_at_utc=attempt.ended_at_utc,
        classification=_classification(attempt),
        source_outcome=attempt.outcome,
        terminal_phase=attempt.terminal_state,
        terminal_reason=attempt.terminal_reason,
        remote_callsign=str(attempt.callsign),
        band=attempt.band,
        dial_frequency_hz=attempt.dial_frequency_hz,
        local_grid=None if attempt.local_grid is None else str(attempt.local_grid),
        local_latitude=attempt.local_latitude,
        local_longitude=attempt.local_longitude,
        remote_grid=None if attempt.remote_grid is None else str(attempt.remote_grid),
        remote_grid_source=(None if attempt.remote_grid is None else "decoded_ft8"),
        reports=tuple(reports),
        tx_periods=tx_periods,
        initial_configured_power_watts=attempt.tx_power_start_watts,
        final_configured_power_watts=attempt.tx_power_end_watts,
        maximum_configured_power_watts=attempt.tx_power_max_watts,
        transmit_attempt_count=attempt.attempt_count,
        busy_extension_attempts=attempt.busy_extension_attempts,
    )


class AttemptDeliveryState(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    RETRY = "retry"
    DELIVERED = "delivered"
    DEAD_LETTER = "dead_letter"


class FT8AttemptLedgerConflict(RuntimeError):
    pass


class FT8AttemptDeliverySink(Protocol):
    def deliver(self, event: FT8AttemptEvent) -> UUID: ...


class FT8AttemptLedgerRepository:
    """Append-only source ledger plus identified delivery leases."""

    def __init__(
        self,
        path: Path,
        *,
        max_attempts: int = 8,
        retry_base: timedelta = timedelta(seconds=30),
        retry_max: timedelta = timedelta(hours=1),
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if retry_base <= timedelta(0) or retry_max < retry_base:
            raise ValueError("retry durations must be positive and ordered")
        self._path = path
        self._max_attempts = max_attempts
        self._retry_base = retry_base
        self._retry_max = retry_max
        self._initialize()

    def capture(self, event: FT8AttemptEvent) -> bool:
        payload = _payload(event)
        digest = event.payload_sha256
        now = _time(event.source_event_created_utc)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT payload_sha256,payload_json FROM ft8_attempt_ledger WHERE attempt_uuid=?",
                (str(event.attempt_uuid),),
            ).fetchone()
            if row is not None:
                if row != (digest, payload):
                    raise FT8AttemptLedgerConflict(
                        f"attempt UUID replay changed immutable event: {event.attempt_uuid}"
                    )
                return False
            db.execute(
                """INSERT INTO ft8_attempt_ledger
                (attempt_uuid,payload_sha256,payload_json,state,delivery_attempt_count,
                 captured_at_utc,next_attempt_at_utc)
                VALUES (?,?,?,'pending',0,?,?)""",
                (str(event.attempt_uuid), digest, payload, now, now),
            )
        return True

    def read(self, attempt_uuid: UUID) -> FT8AttemptEvent | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT payload_json FROM ft8_attempt_ledger WHERE attempt_uuid=?",
                (str(attempt_uuid),),
            ).fetchone()
        return None if row is None else FT8AttemptEvent.model_validate_json(row[0])

    def claim_due(
        self,
        *,
        now_utc: datetime,
        worker_id: str,
        lease_duration: timedelta,
        limit: int = 25,
    ) -> tuple[tuple[FT8AttemptEvent, UUID], ...]:
        now = _utc(now_utc)
        if not worker_id.strip() or len(worker_id) > 120:
            raise ValueError("worker_id must contain 1..120 characters")
        if lease_duration <= timedelta(0) or not 1 <= limit <= _MAX_BATCH:
            raise ValueError("invalid lease duration or batch limit")
        claimed: list[tuple[str, str]] = []
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """UPDATE ft8_attempt_ledger SET state='dead_letter',lease_token=NULL,
                leased_until_utc=NULL,worker_id=NULL,last_error='lease expired after final attempt'
                WHERE state='processing' AND leased_until_utc<=? AND delivery_attempt_count>=?""",
                (_time(now), self._max_attempts),
            )
            rows = db.execute(
                """SELECT attempt_uuid,payload_json,delivery_attempt_count
                FROM ft8_attempt_ledger WHERE
                ((state IN ('pending','retry') AND next_attempt_at_utc<=?) OR
                 (state='processing' AND leased_until_utc<=?))
                AND delivery_attempt_count<?
                ORDER BY next_attempt_at_utc,captured_at_utc,attempt_uuid LIMIT ?""",
                (_time(now), _time(now), self._max_attempts, limit),
            ).fetchall()
            for attempt_uuid, payload, prior in rows:
                token = uuid4()
                db.execute(
                    """UPDATE ft8_attempt_ledger SET state='processing',
                    delivery_attempt_count=?,lease_token=?,leased_until_utc=?,worker_id=?,
                    last_error=NULL WHERE attempt_uuid=?""",
                    (
                        int(prior) + 1,
                        str(token),
                        _time(now + lease_duration),
                        worker_id.strip(),
                        attempt_uuid,
                    ),
                )
                claimed.append((payload, str(token)))
        return tuple(
            (FT8AttemptEvent.model_validate_json(payload), UUID(token))
            for payload, token in claimed
        )

    def mark_delivered(
        self, attempt_uuid: UUID, lease_token: UUID, *, delivered_at_utc: datetime
    ) -> None:
        self._finish(
            attempt_uuid,
            lease_token,
            state=AttemptDeliveryState.DELIVERED,
            now=_utc(delivered_at_utc),
            error=None,
        )

    def mark_failed(
        self,
        attempt_uuid: UUID,
        lease_token: UUID,
        *,
        failed_at_utc: datetime,
        error: str,
    ) -> AttemptDeliveryState:
        now = _utc(failed_at_utc)
        with self._connect() as db:
            row = db.execute(
                "SELECT delivery_attempt_count FROM ft8_attempt_ledger "
                "WHERE attempt_uuid=? AND state='processing' AND lease_token=?",
                (str(attempt_uuid), str(lease_token)),
            ).fetchone()
        if row is None:
            raise RuntimeError("attempt delivery lease is stale")
        terminal = int(row[0]) >= self._max_attempts
        state = AttemptDeliveryState.DEAD_LETTER if terminal else AttemptDeliveryState.RETRY
        self._finish(attempt_uuid, lease_token, state=state, now=now, error=error)
        return state

    def state_for(self, attempt_uuid: UUID) -> AttemptDeliveryState | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT state FROM ft8_attempt_ledger WHERE attempt_uuid=?",
                (str(attempt_uuid),),
            ).fetchone()
        return None if row is None else AttemptDeliveryState(row[0])

    def _finish(
        self,
        attempt_uuid: UUID,
        lease_token: UUID,
        *,
        state: AttemptDeliveryState,
        now: datetime,
        error: str | None,
    ) -> None:
        with self._connect() as db:
            row = db.execute(
                "SELECT delivery_attempt_count FROM ft8_attempt_ledger "
                "WHERE attempt_uuid=? AND state='processing' AND lease_token=?",
                (str(attempt_uuid), str(lease_token)),
            ).fetchone()
            if row is None:
                raise RuntimeError("attempt delivery lease is stale")
            count = int(row[0])
            delay = min(self._retry_base * (2 ** max(0, count - 1)), self._retry_max)
            db.execute(
                """UPDATE ft8_attempt_ledger SET state=?,lease_token=NULL,
                leased_until_utc=NULL,worker_id=NULL,delivered_at_utc=?,
                next_attempt_at_utc=?,last_error=? WHERE attempt_uuid=?""",
                (
                    state.value,
                    _time(now) if state is AttemptDeliveryState.DELIVERED else None,
                    _time(now + delay) if state is AttemptDeliveryState.RETRY else _time(now),
                    None if error is None else (error.strip() or "unknown error")[:_MAX_ERROR],
                    str(attempt_uuid),
                ),
            )

    def _initialize(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=NORMAL")
            db.executescript(
                """CREATE TABLE IF NOT EXISTS ft8_attempt_ledger (
                attempt_uuid TEXT PRIMARY KEY,payload_sha256 TEXT NOT NULL,
                payload_json TEXT NOT NULL,state TEXT NOT NULL CHECK(state IN
                ('pending','processing','retry','delivered','dead_letter')),
                delivery_attempt_count INTEGER NOT NULL CHECK(delivery_attempt_count>=0),
                captured_at_utc TEXT NOT NULL,next_attempt_at_utc TEXT NOT NULL,
                lease_token TEXT,leased_until_utc TEXT,worker_id TEXT,
                delivered_at_utc TEXT,last_error TEXT);
                CREATE INDEX IF NOT EXISTS ft8_attempt_ledger_due
                ON ft8_attempt_ledger(state,next_attempt_at_utc);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self._path, timeout=5)
        db.execute("PRAGMA busy_timeout=5000")
        db.execute("PRAGMA foreign_keys=ON")
        return db


class FT8AttemptDeliveryWorker:
    def __init__(
        self,
        repository: FT8AttemptLedgerRepository,
        sink: FT8AttemptDeliverySink,
        *,
        worker_id: str,
        batch_size: int = 25,
        lease_duration: timedelta = timedelta(minutes=2),
    ) -> None:
        self._repository = repository
        self._sink = sink
        self._worker_id = worker_id
        self._batch_size = batch_size
        self._lease_duration = lease_duration

    def run_once(self, *, now_utc: datetime) -> tuple[int, int]:
        delivered = failed = 0
        for event, token in self._repository.claim_due(
            now_utc=now_utc,
            worker_id=self._worker_id,
            lease_duration=self._lease_duration,
            limit=self._batch_size,
        ):
            try:
                acknowledged = self._sink.deliver(event)
                if acknowledged != event.attempt_uuid:
                    raise ValueError("Forge acknowledged a different attempt UUID")
                self._repository.mark_delivered(
                    event.attempt_uuid, token, delivered_at_utc=now_utc
                )
                delivered += 1
            except Exception as error:  # noqa: BLE001 - delivery jobs are isolated
                self._repository.mark_failed(
                    event.attempt_uuid,
                    token,
                    failed_at_utc=now_utc,
                    error=str(error) or error.__class__.__name__,
                )
                failed += 1
        return delivered, failed


class FT8AttemptDeliveryService:
    """Schedule independent store-forward work outside terminal and UI paths."""

    def __init__(
        self,
        worker: FT8AttemptDeliveryWorker,
        scheduler: PollScheduler,
        *,
        interval_s: float,
    ) -> None:
        if interval_s <= 0:
            raise ValueError("attempt delivery interval must be positive")
        self._worker = worker
        self._scheduler = scheduler
        self._interval_s = interval_s
        self._scheduled: ScheduledPoll | None = None

    def start(self) -> None:
        if self._scheduled is not None:
            raise RuntimeError("attempt delivery is already running")
        self._scheduled = self._scheduler.schedule_repeating(
            self._interval_s, self._run_once
        )

    def stop(self) -> None:
        scheduled = self._scheduled
        self._scheduled = None
        if scheduled is not None:
            scheduled.cancel()

    def _run_once(self) -> None:
        try:
            self._worker.run_once(now_utc=datetime.now(UTC))
        except (OSError, RuntimeError, sqlite3.Error, ValueError) as error:
            _LOGGER.error("FT8 attempt delivery cycle failed: %s", error)


def _classification(attempt: FT8PerformanceAttempt) -> FT8AttemptClassification:
    if attempt.outcome is FT8AttemptOutcome.COMPLETED:
        return FT8AttemptClassification.SUCCESS
    if attempt.outcome is FT8AttemptOutcome.ABORTED:
        return FT8AttemptClassification.ABORT
    if attempt.outcome is FT8AttemptOutcome.RETRY_EXHAUSTED:
        return (
            FT8AttemptClassification.BUSY
            if attempt.busy_extension_attempts
            else FT8AttemptClassification.NO_ANSWER
        )
    reason = (attempt.terminal_reason or "").lower()
    if any(word in reason for word in ("context", "shutdown", "cancel", "interrupt")):
        return FT8AttemptClassification.INTERRUPTION
    return FT8AttemptClassification.FAULT


def _payload(event: FT8AttemptEvent) -> str:
    return dumps(event.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _time(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")
