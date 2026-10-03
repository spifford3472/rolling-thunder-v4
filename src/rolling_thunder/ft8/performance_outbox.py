"""Restart-safe local outbox for FT8 performance telemetry."""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from json import dumps, loads
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

from rolling_thunder.ft8.performance import FT8PerformanceAttempt
from rolling_thunder.storage import StorageError, initialize_database


class FT8PerformanceSyncState(StrEnum):
    PENDING = "pending"
    SYNCHRONIZED = "synchronized"
    FAILED = "failed"


class FT8PerformanceConflictError(StorageError):
    """Raised when one attempt UUID is replayed with different telemetry."""


class FT8PerformanceOutboxRepository:
    """Persist terminal telemetry locally before any network delivery."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        initialize_database(database_path)

    def add_idempotent(self, attempt: FT8PerformanceAttempt) -> FT8PerformanceAttempt:
        """Store one immutable attempt or accept an identical replay."""
        payload = self._payload(attempt)
        try:
            with sqlite3.connect(self._database_path) as connection:
                row = connection.execute(
                    """
                    SELECT payload_json
                    FROM ft8_performance_outbox
                    WHERE attempt_id = ?
                    """,
                    (str(attempt.attempt_id),),
                ).fetchone()
                if row is None:
                    connection.execute(
                        """
                        INSERT INTO ft8_performance_outbox (
                            attempt_id,
                            payload_json,
                            synchronization_state
                        )
                        VALUES (?, ?, ?)
                        """,
                        (
                            str(attempt.attempt_id),
                            payload,
                            FT8PerformanceSyncState.PENDING.value,
                        ),
                    )
                    connection.commit()
                    return attempt
                if row[0] != payload:
                    raise FT8PerformanceConflictError(
                        "FT8 attempt idempotency key was reused with different telemetry: "
                        f"{attempt.attempt_id}"
                    )
        except FT8PerformanceConflictError:
            raise
        except sqlite3.Error as error:
            raise StorageError(
                f"FT8 performance attempt could not be stored: {attempt.attempt_id}: {error}"
            ) from error
        return attempt

    def list_for_utc_date(self, utc_date: date) -> list[FT8PerformanceAttempt]:
        """Return all stored attempts whose payload belongs to one UTC date."""
        try:
            with sqlite3.connect(self._database_path) as connection:
                rows = connection.execute(
                    """
                    SELECT payload_json
                    FROM ft8_performance_outbox
                    ORDER BY created_at ASC, attempt_id ASC
                    """
                ).fetchall()
        except sqlite3.Error as error:
            raise StorageError(
                f"FT8 performance history could not be read: {error}"
            ) from error
        attempts = [self._decode(row[0]) for row in rows]
        return [attempt for attempt in attempts if attempt.utc_date == utc_date]

    def list_ready(
        self,
        now: datetime,
        *,
        limit: int = 50,
    ) -> list[FT8PerformanceAttempt]:
        """List pending or retry-due attempts oldest first."""
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        if type(limit) is not int:
            raise TypeError("limit must be an integer")
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        now_text = now.astimezone(UTC).isoformat().replace("+00:00", "Z")
        try:
            with sqlite3.connect(self._database_path) as connection:
                rows = connection.execute(
                    """
                    SELECT payload_json
                    FROM ft8_performance_outbox
                    WHERE synchronization_state = 'pending'
                       OR (
                            synchronization_state = 'failed'
                            AND next_attempt_at IS NOT NULL
                            AND next_attempt_at <= ?
                       )
                    ORDER BY created_at ASC, attempt_id ASC
                    LIMIT ?
                    """,
                    (now_text, limit),
                ).fetchall()
        except sqlite3.Error as error:
            raise StorageError(
                f"FT8 performance outbox could not be listed: {error}"
            ) from error
        return [self._decode(row[0]) for row in rows]

    def mark_synchronized(self, attempt_id: UUID) -> None:
        """Mark one attempt as durably accepted by Forge."""
        self._update_state(
            attempt_id,
            state=FT8PerformanceSyncState.SYNCHRONIZED,
            retry_count=None,
            next_attempt_at=None,
            last_error=None,
        )

    def record_failure(
        self,
        attempt_id: UUID,
        error: str,
        *,
        now: datetime,
        initial_delay_s: float = 5.0,
        maximum_delay_s: float = 300.0,
    ) -> None:
        """Record exponential retry metadata after a Forge upload failure."""
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        if initial_delay_s <= 0 or maximum_delay_s <= 0:
            raise ValueError("retry delays must be positive")
        if maximum_delay_s < initial_delay_s:
            raise ValueError("maximum retry delay must not be below initial delay")

        normalized_error = error.strip()
        if not normalized_error:
            raise ValueError("error must not be blank")
        normalized_error = normalized_error[:1000]

        try:
            with sqlite3.connect(self._database_path) as connection:
                row = connection.execute(
                    """
                    SELECT retry_count
                    FROM ft8_performance_outbox
                    WHERE attempt_id = ?
                    """,
                    (str(attempt_id),),
                ).fetchone()
                if row is None:
                    raise StorageError(
                        f"FT8 performance attempt does not exist: {attempt_id}"
                    )
                retry_count = int(row[0]) + 1
                delay_s = min(
                    maximum_delay_s,
                    initial_delay_s * (2 ** (retry_count - 1)),
                )
                next_attempt = (
                    now.astimezone(UTC) + timedelta(seconds=delay_s)
                ).isoformat().replace("+00:00", "Z")
                connection.execute(
                    """
                    UPDATE ft8_performance_outbox
                    SET synchronization_state = 'failed',
                        retry_count = ?,
                        next_attempt_at = ?,
                        last_error = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE attempt_id = ?
                    """,
                    (
                        retry_count,
                        next_attempt,
                        normalized_error,
                        str(attempt_id),
                    ),
                )
                connection.commit()
        except StorageError:
            raise
        except sqlite3.Error as sqlite_error:
            raise StorageError(
                f"FT8 performance retry state could not be stored: {attempt_id}: "
                f"{sqlite_error}"
            ) from sqlite_error

    def state_for(self, attempt_id: UUID) -> FT8PerformanceSyncState | None:
        """Return synchronization state for tests/diagnostics."""
        try:
            with sqlite3.connect(self._database_path) as connection:
                row = connection.execute(
                    """
                    SELECT synchronization_state
                    FROM ft8_performance_outbox
                    WHERE attempt_id = ?
                    """,
                    (str(attempt_id),),
                ).fetchone()
        except sqlite3.Error as error:
            raise StorageError(
                f"FT8 performance state could not be read: {attempt_id}: {error}"
            ) from error
        return None if row is None else FT8PerformanceSyncState(row[0])

    def _update_state(
        self,
        attempt_id: UUID,
        *,
        state: FT8PerformanceSyncState,
        retry_count: int | None,
        next_attempt_at: str | None,
        last_error: str | None,
    ) -> None:
        try:
            with sqlite3.connect(self._database_path) as connection:
                if retry_count is None:
                    result = connection.execute(
                        """
                        UPDATE ft8_performance_outbox
                        SET synchronization_state = ?,
                            next_attempt_at = ?,
                            last_error = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE attempt_id = ?
                        """,
                        (
                            state.value,
                            next_attempt_at,
                            last_error,
                            str(attempt_id),
                        ),
                    )
                else:
                    result = connection.execute(
                        """
                        UPDATE ft8_performance_outbox
                        SET synchronization_state = ?,
                            retry_count = ?,
                            next_attempt_at = ?,
                            last_error = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE attempt_id = ?
                        """,
                        (
                            state.value,
                            retry_count,
                            next_attempt_at,
                            last_error,
                            str(attempt_id),
                        ),
                    )
                if result.rowcount != 1:
                    raise StorageError(
                        f"FT8 performance attempt does not exist: {attempt_id}"
                    )
                connection.commit()
        except StorageError:
            raise
        except sqlite3.Error as error:
            raise StorageError(
                f"FT8 performance state could not be updated: {attempt_id}: {error}"
            ) from error

    @staticmethod
    def _payload(attempt: FT8PerformanceAttempt) -> str:
        return dumps(
            attempt.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )

    @staticmethod
    def _decode(payload: str) -> FT8PerformanceAttempt:
        try:
            return FT8PerformanceAttempt.model_validate(loads(payload))
        except (ValueError, ValidationError) as error:
            raise StorageError("Stored FT8 performance payload is invalid") from error
