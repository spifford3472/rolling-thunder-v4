"""Persistent exponential-backoff metadata for contact synchronization."""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from pydantic import Field

from rolling_thunder.domain import DomainModel
from rolling_thunder.storage import StorageError, initialize_database


class ContactRetryRecord(DomainModel):
    """Immutable persisted retry eligibility for one contact."""

    contact_id: UUID
    attempt_count: int = Field(ge=1)
    next_attempt_at: datetime
    last_error: str = Field(min_length=1)


class ContactRetryRepository:
    """Store and query restart-safe contact synchronization retries."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        initialize_database(database_path)

    def record_failure(
        self,
        contact_id: UUID,
        *,
        failed_at: datetime,
        error_message: str,
        initial_delay_s: float,
        max_delay_s: float,
    ) -> ContactRetryRecord:
        """Advance one contact's exponential backoff and persist its due time."""
        timestamp = self._require_aware(failed_at)
        if initial_delay_s <= 0 or max_delay_s <= 0:
            raise ValueError("Retry delays must be positive.")
        if max_delay_s < initial_delay_s:
            raise ValueError("Maximum retry delay must not be below the initial delay.")
        normalized_error = error_message.strip()
        if not normalized_error:
            raise ValueError("Retry error message must not be empty.")

        try:
            with sqlite3.connect(self._database_path) as connection:
                existing = connection.execute(
                    "SELECT attempt_count FROM contact_sync_retries WHERE contact_id = ?",
                    (str(contact_id),),
                ).fetchone()
                attempt_count = 1 if existing is None else int(existing[0]) + 1
                # Double a bounded delay rather than computing 2 ** attempt_count.
                # Persisted contacts can have hundreds or thousands of failures;
                # converting such an integer to float previously overflowed.
                delay_s = initial_delay_s
                remaining_doublings = attempt_count - 1
                while remaining_doublings > 0 and delay_s < max_delay_s:
                    delay_s = min(delay_s * 2.0, max_delay_s)
                    remaining_doublings -= 1
                next_attempt_at = timestamp + timedelta(seconds=delay_s)
                connection.execute(
                    """
                    INSERT INTO contact_sync_retries (
                        contact_id, attempt_count, next_attempt_at, last_error
                    ) VALUES (?, ?, ?, ?)
                    ON CONFLICT(contact_id) DO UPDATE SET
                        attempt_count = excluded.attempt_count,
                        next_attempt_at = excluded.next_attempt_at,
                        last_error = excluded.last_error,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        str(contact_id),
                        attempt_count,
                        next_attempt_at.isoformat().replace("+00:00", "Z"),
                        normalized_error,
                    ),
                )
                connection.commit()
        except sqlite3.Error as error:
            raise StorageError(
                f"Contact retry metadata could not be stored: {contact_id}: {error}"
            ) from error

        return ContactRetryRecord(
            contact_id=contact_id,
            attempt_count=attempt_count,
            next_attempt_at=next_attempt_at,
            last_error=normalized_error,
        )

    def list_due_contact_ids(self, due_at: datetime, *, limit: int) -> list[UUID]:
        """Return failed contact IDs whose persisted retry time has arrived."""
        timestamp = self._require_aware(due_at)
        if limit < 1:
            raise ValueError("Retry candidate limit must be positive.")
        try:
            with sqlite3.connect(self._database_path) as connection:
                rows = connection.execute(
                    """
                    SELECT retries.contact_id
                    FROM contact_sync_retries AS retries
                    JOIN contacts ON contacts.contact_id = retries.contact_id
                    WHERE contacts.synchronization_state = 'failed'
                      AND retries.next_attempt_at <= ?
                    ORDER BY retries.next_attempt_at ASC, retries.contact_id ASC
                    LIMIT ?
                    """,
                    (timestamp.isoformat().replace("+00:00", "Z"), limit),
                ).fetchall()
        except sqlite3.Error as error:
            raise StorageError(f"Due contact retries could not be listed: {error}") from error
        return [UUID(str(row[0])) for row in rows]

    def clear(self, contact_id: UUID) -> None:
        """Remove retry metadata after a successful upload."""
        try:
            with sqlite3.connect(self._database_path) as connection:
                connection.execute(
                    "DELETE FROM contact_sync_retries WHERE contact_id = ?",
                    (str(contact_id),),
                )
                connection.commit()
        except sqlite3.Error as error:
            raise StorageError(
                f"Contact retry metadata could not be cleared: {contact_id}: {error}"
            ) from error

    @staticmethod
    def _require_aware(timestamp: datetime) -> datetime:
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("Retry timestamps must be timezone-aware.")
        return timestamp.astimezone(UTC)
