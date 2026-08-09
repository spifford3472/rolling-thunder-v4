"""SQLite persistence for the Pi's latest valid retained Forge weather."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from pydantic import ValidationError

from rolling_thunder.forge_weather_client import ForgeWeatherClientResult
from rolling_thunder.storage import StorageError, initialize_database


class ForgeWeatherCacheRepository:
    """Transactionally replace and revalidate one last-good weather result."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        initialize_database(database_path)

    def replace(self, result: ForgeWeatherClientResult) -> None:
        """Persist one complete weather result before it may be published."""
        if result.snapshot is None:
            raise StorageError("Forge weather cache only accepts results containing a snapshot.")

        payload = result.model_dump_json()
        try:
            with sqlite3.connect(self._database_path) as connection:
                connection.execute("BEGIN")
                connection.execute("DELETE FROM forge_weather_cache")
                connection.execute(
                    """
                    INSERT INTO forge_weather_cache (
                        singleton_id,
                        revision,
                        source_at,
                        received_at,
                        payload_json
                    )
                    VALUES (1, ?, ?, ?, ?)
                    """,
                    (
                        result.revision,
                        result.snapshot.source_at.isoformat().replace("+00:00", "Z"),
                        result.received_at.isoformat().replace("+00:00", "Z"),
                        payload,
                    ),
                )
                connection.commit()
        except sqlite3.Error as error:
            raise StorageError(
                f"Forge weather cache could not be replaced in {self._database_path}: {error}"
            ) from error

    def load(self) -> ForgeWeatherClientResult | None:
        """Load and fully revalidate the durable last-good weather result."""
        try:
            with sqlite3.connect(self._database_path) as connection:
                row = connection.execute(
                    """
                    SELECT revision, source_at, received_at, payload_json
                    FROM forge_weather_cache
                    WHERE singleton_id = 1
                    """
                ).fetchone()
        except sqlite3.Error as error:
            raise StorageError(
                f"Forge weather cache could not be read from {self._database_path}: {error}"
            ) from error

        if row is None:
            return None

        revision, source_at, received_at, payload_json = row
        if isinstance(revision, bool) or not isinstance(revision, int) or revision <= 0:
            raise StorageError(
                f"Forge weather cache contains invalid revision data in {self._database_path}."
            )
        if not all(isinstance(value, str) for value in (source_at, received_at, payload_json)):
            raise StorageError(
                f"Forge weather cache contains invalid text data in {self._database_path}."
            )

        try:
            result = ForgeWeatherClientResult.model_validate_json(payload_json)
        except (ValidationError, ValueError, TypeError) as error:
            raise StorageError(
                f"Forge weather cache contains invalid data in {self._database_path}: {error}"
            ) from error

        if result.snapshot is None:
            raise StorageError(
                f"Forge weather cache contains a snapshot-less result in {self._database_path}."
            )
        expected_source = result.snapshot.source_at.isoformat().replace("+00:00", "Z")
        expected_received = result.received_at.isoformat().replace("+00:00", "Z")
        if revision != result.revision or source_at != expected_source or received_at != expected_received:
            raise StorageError(
                f"Forge weather cache metadata does not match its payload in {self._database_path}."
            )
        return result
