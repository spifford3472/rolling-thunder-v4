"""SQLite persistence for the Pi's last complete Forge alert result."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from pydantic import ValidationError

from rolling_thunder.forge_weather_alert_client import (
    ForgeWeatherAlertClientResult,
)
from rolling_thunder.storage import StorageError, initialize_database


class ForgeWeatherAlertCacheRepository:
    """Replace and revalidate one complete retained alert result."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        initialize_database(database_path)

    def replace(
        self,
        result: ForgeWeatherAlertClientResult,
    ) -> None:
        """Persist a complete snapshot before application publication."""
        if result.snapshot is None:
            raise StorageError(
                "Forge weather-alert cache requires a snapshot."
            )

        payload = result.model_dump_json()
        fetched_at = (
            result.snapshot.fetched_at
            .isoformat()
            .replace("+00:00", "Z")
        )
        received_at = (
            result.received_at
            .isoformat()
            .replace("+00:00", "Z")
        )

        try:
            with sqlite3.connect(self._database_path) as connection:
                connection.execute("BEGIN")
                connection.execute(
                    "DELETE FROM forge_weather_alert_cache"
                )
                connection.execute(
                    """
                    INSERT INTO forge_weather_alert_cache (
                        singleton_id,
                        revision,
                        fetched_at,
                        received_at,
                        payload_json
                    )
                    VALUES (1, ?, ?, ?, ?)
                    """,
                    (
                        result.revision,
                        fetched_at,
                        received_at,
                        payload,
                    ),
                )
                connection.commit()
        except sqlite3.Error as error:
            raise StorageError(
                "Forge weather-alert cache could not be replaced in "
                f"{self._database_path}: {error}"
            ) from error

    def load(self) -> ForgeWeatherAlertClientResult | None:
        """Load and fully revalidate the durable alert result."""
        try:
            with sqlite3.connect(self._database_path) as connection:
                row = connection.execute(
                    """
                    SELECT
                        revision,
                        fetched_at,
                        received_at,
                        payload_json
                    FROM forge_weather_alert_cache
                    WHERE singleton_id = 1
                    """
                ).fetchone()
        except sqlite3.Error as error:
            raise StorageError(
                "Forge weather-alert cache could not be read from "
                f"{self._database_path}: {error}"
            ) from error

        if row is None:
            return None

        revision, fetched_at, received_at, payload_json = row

        if (
            isinstance(revision, bool)
            or not isinstance(revision, int)
            or revision <= 0
        ):
            raise StorageError(
                "Forge weather-alert cache contains invalid revision "
                f"data in {self._database_path}."
            )

        if not all(
            isinstance(value, str)
            for value in (
                fetched_at,
                received_at,
                payload_json,
            )
        ):
            raise StorageError(
                "Forge weather-alert cache contains invalid text "
                f"data in {self._database_path}."
            )

        try:
            result = (
                ForgeWeatherAlertClientResult
                .model_validate_json(payload_json)
            )
        except (
            ValidationError,
            ValueError,
            TypeError,
        ) as error:
            raise StorageError(
                "Forge weather-alert cache contains invalid data in "
                f"{self._database_path}: {error}"
            ) from error

        if result.snapshot is None:
            raise StorageError(
                "Forge weather-alert cache contains a "
                "snapshot-less result."
            )

        expected_fetched = (
            result.snapshot.fetched_at
            .isoformat()
            .replace("+00:00", "Z")
        )
        expected_received = (
            result.received_at
            .isoformat()
            .replace("+00:00", "Z")
        )

        if (
            revision != result.revision
            or fetched_at != expected_fetched
            or received_at != expected_received
        ):
            raise StorageError(
                "Forge weather-alert cache metadata does not match "
                f"its payload in {self._database_path}."
            )

        return result
