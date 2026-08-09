"""Durable once-per-alert audible notification claim ledger."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from rolling_thunder.storage import StorageError, initialize_database


class WeatherAlertNotificationRepository:
    """Atomically claim provider alert IDs before audible playback."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        initialize_database(database_path)

    def claim(
        self,
        alert_id: str,
        event: str,
        *,
        claimed_at: datetime,
    ) -> bool:
        """Return True only for the first durable claim of an alert ID."""
        normalized_id = " ".join(alert_id.split())
        normalized_event = " ".join(event.split())

        if not normalized_id:
            raise ValueError("Weather alert ID must not be blank.")
        if len(normalized_id) > 512:
            raise ValueError(
                "Weather alert ID must not exceed 512 characters."
            )
        if not normalized_event:
            raise ValueError("Weather alert event must not be blank.")
        if len(normalized_event) > 160:
            raise ValueError(
                "Weather alert event must not exceed 160 characters."
            )
        if (
            claimed_at.tzinfo is None
            or claimed_at.utcoffset() is None
        ):
            raise ValueError(
                "Weather alert claimed_at must be timezone-aware."
            )

        claimed_text = (
            claimed_at.astimezone(UTC)
            .isoformat()
            .replace("+00:00", "Z")
        )

        try:
            with sqlite3.connect(self._database_path) as connection:
                connection.execute("BEGIN IMMEDIATE")
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO
                        weather_alert_notification_ledger (
                            alert_id,
                            event,
                            claimed_at
                        )
                    VALUES (?, ?, ?)
                    """,
                    (
                        normalized_id,
                        normalized_event,
                        claimed_text,
                    ),
                )
                claimed = cursor.rowcount == 1
                connection.commit()
        except sqlite3.Error as error:
            raise StorageError(
                "Weather-alert notification claim could not be "
                f"persisted in {self._database_path}: {error}"
            ) from error

        return claimed

    def is_claimed(self, alert_id: str) -> bool:
        """Return whether this stable provider alert ID was already claimed."""
        normalized_id = " ".join(alert_id.split())
        if not normalized_id:
            raise ValueError("Weather alert ID must not be blank.")

        try:
            with sqlite3.connect(self._database_path) as connection:
                row = connection.execute(
                    """
                    SELECT 1
                    FROM weather_alert_notification_ledger
                    WHERE alert_id = ?
                    """,
                    (normalized_id,),
                ).fetchone()
        except sqlite3.Error as error:
            raise StorageError(
                "Weather-alert notification ledger could not be read "
                f"from {self._database_path}: {error}"
            ) from error

        return row is not None
