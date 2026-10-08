"""Forge-local orchestration and observable state for completed-QSO correlation."""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from threading import Lock
from typing import Literal, Protocol
from uuid import uuid4

from pydantic import Field, field_validator

from rolling_thunder.domain import DomainModel
from rolling_thunder.forge_propagation_qso_ingestion import (
    CompletedQsoCorrelationWorker,
    CompletedQsoIngestionRepository,
    CompletedQsoQueueSnapshot,
    CompletedQsoWorkResult,
)


class CompletedQsoWorkerCycleState(StrEnum):
    IDLE = "idle"
    SUCCEEDED = "succeeded"
    DEGRADED = "degraded"


class CompletedQsoWorkerSnapshot(DomainModel):
    """Versioned status from one bounded worker cycle."""

    schema_version: Literal["1"] = "1"
    service: Literal["forge-propagation-qso-worker"] = "forge-propagation-qso-worker"
    worker_identity: str = Field(min_length=1, max_length=120)
    cycle_state: CompletedQsoWorkerCycleState
    started_at_utc: datetime
    completed_at_utc: datetime
    results: tuple[CompletedQsoWorkResult, ...] = ()
    queue: CompletedQsoQueueSnapshot

    @field_validator("started_at_utc", "completed_at_utc")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("worker timestamps must be timezone-aware")
        return value.astimezone(UTC)


class CompletedQsoWorkerStatusPublisher(Protocol):
    def publish(self, snapshot: CompletedQsoWorkerSnapshot) -> None: ...


class JsonFileCompletedQsoWorkerStatusPublisher:
    """Atomically publish non-secret worker state to a Forge-local JSON file."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def publish(self, snapshot: CompletedQsoWorkerSnapshot) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_name(f".{self._path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(snapshot.model_dump_json(indent=2) + "\n", encoding="utf-8")
            os.replace(temporary, self._path)
        finally:
            temporary.unlink(missing_ok=True)


class CompletedQsoWorkerOrchestrator:
    """Run and publish one bounded cycle with injected deterministic time."""

    def __init__(
        self,
        repository: CompletedQsoIngestionRepository,
        worker: CompletedQsoCorrelationWorker,
        *,
        worker_identity: str,
        publisher: CompletedQsoWorkerStatusPublisher,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        identity = worker_identity.strip()
        if not identity:
            raise ValueError("worker_identity must not be blank")
        if len(identity) > 120:
            raise ValueError("worker_identity must not exceed 120 characters")
        self._repository = repository
        self._worker = worker
        self._worker_identity = identity
        self._publisher = publisher
        self._clock = clock
        self._latest: CompletedQsoWorkerSnapshot | None = None
        self._lock = Lock()

    def run_once(self) -> CompletedQsoWorkerSnapshot:
        started_at = self._clock()
        results = self._worker.run_due(now_utc=started_at)
        completed_at = self._clock()
        queue = self._repository.observe(now_utc=completed_at)
        if (
            any(result.error is not None for result in results)
            or queue.retry_count > 0
            or queue.dead_letter_count > 0
        ):
            state = CompletedQsoWorkerCycleState.DEGRADED
        elif not results:
            state = CompletedQsoWorkerCycleState.IDLE
        else:
            state = CompletedQsoWorkerCycleState.SUCCEEDED
        snapshot = CompletedQsoWorkerSnapshot(
            worker_identity=self._worker_identity,
            cycle_state=state,
            started_at_utc=started_at,
            completed_at_utc=completed_at,
            results=results,
            queue=queue,
        )
        self._publisher.publish(snapshot)
        with self._lock:
            self._latest = snapshot
        return snapshot

    def latest_snapshot(self) -> CompletedQsoWorkerSnapshot | None:
        with self._lock:
            return self._latest
