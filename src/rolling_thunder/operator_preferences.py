"""Typed SQLite-backed operator preferences with nonblocking persistence."""

from __future__ import annotations

import sqlite3
from concurrent.futures import Executor, ThreadPoolExecutor
from enum import StrEnum
from pathlib import Path
from threading import Lock

from rolling_thunder.storage import StorageError, initialize_database


class OperatorPreferenceKey(StrEnum):
    """Stable keys for mutable operator preferences."""

    MAP_ZOOM = "map.zoom"


class OperatorPreferenceRepository:
    """Read and write typed mutable operator preferences in application SQLite."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        initialize_database(database_path)

    def read_map_zoom(self) -> int | None:
        """Return a valid stored map zoom, or None for missing/malformed data."""
        raw = self._read_text(OperatorPreferenceKey.MAP_ZOOM)
        if raw is None:
            return None
        try:
            zoom = int(raw)
        except ValueError:
            return None
        if not 0 <= zoom <= 22:
            return None
        return zoom

    def write_map_zoom(self, zoom: int) -> None:
        """Persist one validated map zoom atomically."""
        if not 0 <= zoom <= 22:
            raise ValueError("Map zoom preference must be between 0 and 22.")
        self._write_text(OperatorPreferenceKey.MAP_ZOOM, str(zoom))

    def _read_text(self, key: OperatorPreferenceKey) -> str | None:
        try:
            with sqlite3.connect(self._database_path) as connection:
                row = connection.execute(
                    """
                    SELECT preference_value
                    FROM operator_preferences
                    WHERE preference_key = ?
                    """,
                    (key.value,),
                ).fetchone()
        except sqlite3.Error as error:
            raise StorageError(
                f"Operator preference could not be read: {key.value}: {error}"
            ) from error

        if row is None:
            return None
        value = row[0]
        return value if isinstance(value, str) else None

    def _write_text(self, key: OperatorPreferenceKey, value: str) -> None:
        try:
            with sqlite3.connect(self._database_path) as connection:
                connection.execute(
                    """
                    INSERT INTO operator_preferences (
                        preference_key,
                        preference_value,
                        updated_at
                    )
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(preference_key) DO UPDATE SET
                        preference_value = excluded.preference_value,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (key.value, value),
                )
                connection.commit()
        except sqlite3.Error as error:
            raise StorageError(
                f"Operator preference could not be stored: {key.value}: {error}"
            ) from error


class OperatorPreferenceService:
    """Queue short preference writes away from the Tkinter/UI thread."""

    def __init__(
        self,
        repository: OperatorPreferenceRepository,
        *,
        executor: Executor | None = None,
    ) -> None:
        self._repository = repository
        self._executor = executor
        self._owns_executor = executor is None
        self._lock = Lock()
        self._last_error: str | None = None
        self._stopped = False

    @property
    def last_error(self) -> str | None:
        """Return the most recent asynchronous persistence error, if any."""
        with self._lock:
            return self._last_error

    def persist_map_zoom(self, zoom: int) -> bool:
        """Queue one map-zoom write without blocking the caller."""
        if not 0 <= zoom <= 22:
            raise ValueError("Map zoom preference must be between 0 and 22.")

        with self._lock:
            if self._stopped:
                return False
            if self._executor is None:
                self._executor = ThreadPoolExecutor(
                    max_workers=1,
                    thread_name_prefix="rolling-thunder-preferences",
                )
            executor = self._executor

        executor.submit(self._write_map_zoom_safely, zoom)
        return True

    def stop(self) -> None:
        """Stop accepting writes without blocking dashboard shutdown."""
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            executor = self._executor
            self._executor = None

        if executor is not None and self._owns_executor:
            executor.shutdown(wait=False, cancel_futures=False)

    def _write_map_zoom_safely(self, zoom: int) -> None:
        try:
            self._repository.write_map_zoom(zoom)
        except (StorageError, ValueError) as error:
            with self._lock:
                self._last_error = str(error)
            return

        with self._lock:
            self._last_error = None
