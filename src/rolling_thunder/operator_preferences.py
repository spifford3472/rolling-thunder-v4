"""Typed SQLite-backed operator preferences with nonblocking persistence."""

from __future__ import annotations

import sqlite3
from concurrent.futures import Executor, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from enum import StrEnum
from pathlib import Path
from threading import Lock

from rolling_thunder.map_zoom import (
    OPERATOR_MAXIMUM_MAP_ZOOM,
    OPERATOR_MINIMUM_MAP_ZOOM,
)
from rolling_thunder.storage import StorageError, initialize_database


class OperatorPreferenceKey(StrEnum):
    """Stable keys for mutable operator preferences."""

    MAP_ZOOM = "map.zoom"
    RADAR_IMAGE_ENABLED = "radar.image.enabled"
    CALLSIGN_INFO_ENABLED = "callsign.info.enabled"


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
        if not OPERATOR_MINIMUM_MAP_ZOOM <= zoom <= OPERATOR_MAXIMUM_MAP_ZOOM:
            return None
        return zoom

    def write_map_zoom(self, zoom: int) -> None:
        """Persist one validated map zoom atomically."""
        if not OPERATOR_MINIMUM_MAP_ZOOM <= zoom <= OPERATOR_MAXIMUM_MAP_ZOOM:
            raise ValueError(
                "Map zoom preference must be between "
                f"{OPERATOR_MINIMUM_MAP_ZOOM} and {OPERATOR_MAXIMUM_MAP_ZOOM}."
            )
        self._write_text(OperatorPreferenceKey.MAP_ZOOM, str(zoom))

    def read_radar_image_enabled(self) -> bool | None:
        """Return the stored radar-image choice, or None when missing/malformed."""
        raw = self._read_text(OperatorPreferenceKey.RADAR_IMAGE_ENABLED)
        if raw == "1":
            return True
        if raw == "0":
            return False
        return None

    def write_radar_image_enabled(self, enabled: bool) -> None:
        """Persist the operator's Pi-side radar-image choice atomically."""
        self._write_text(
            OperatorPreferenceKey.RADAR_IMAGE_ENABLED,
            "1" if enabled else "0",
        )

    def read_callsign_info_enabled(self) -> bool | None:
        """Return stored callsign-info visibility choice, or None when absent."""
        raw = self._read_text(OperatorPreferenceKey.CALLSIGN_INFO_ENABLED)
        if raw == "1":
            return True
        if raw == "0":
            return False
        return None

    def write_callsign_info_enabled(self, enabled: bool) -> None:
        """Persist the operator's callsign-info choice atomically."""
        self._write_text(
            OperatorPreferenceKey.CALLSIGN_INFO_ENABLED,
            "1" if enabled else "0",
        )

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
        self._errors: dict[OperatorPreferenceKey, str] = {}
        self._stopped = False

    @property
    def last_error(self) -> str | None:
        """Return the most recent asynchronous persistence error, if any."""
        with self._lock:
            return next(iter(self._errors.values()), None)

    def persist_map_zoom(self, zoom: int) -> bool:
        """Queue one map-zoom write without blocking the caller."""
        if not OPERATOR_MINIMUM_MAP_ZOOM <= zoom <= OPERATOR_MAXIMUM_MAP_ZOOM:
            raise ValueError(
                "Map zoom preference must be between "
                f"{OPERATOR_MINIMUM_MAP_ZOOM} and {OPERATOR_MAXIMUM_MAP_ZOOM}."
            )
        executor = self._write_executor()
        if executor is None:
            return False
        try:
            executor.submit(self._write_map_zoom_safely, zoom)
        except RuntimeError:
            return False
        return True

    def persist_radar_image_enabled(self, enabled: bool) -> bool:
        """Queue one radar-image preference write without blocking the caller."""
        executor = self._write_executor()
        if executor is None:
            return False
        try:
            executor.submit(self._write_radar_image_safely, enabled)
        except RuntimeError:
            return False
        return True

    def persist_callsign_info_enabled(self, enabled: bool) -> bool:
        """Queue one callsign-info preference write without blocking the caller."""
        executor = self._write_executor()
        if executor is None:
            return False
        try:
            executor.submit(self._write_callsign_info_safely, enabled)
        except RuntimeError:
            return False
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

    def flush(self, timeout_s: float) -> bool:
        """Boundedly wait for queued writes without stopping preference service."""
        if isinstance(timeout_s, bool) or not 0 < timeout_s <= 3:
            raise ValueError("Preference flush timeout must be within (0, 3] seconds.")
        executor = self._write_executor()
        if executor is None:
            return False
        try:
            executor.submit(lambda: None).result(timeout=timeout_s)
        except (FutureTimeoutError, RuntimeError):
            return False
        with self._lock:
            return not self._errors

    def _write_executor(self) -> Executor | None:
        with self._lock:
            if self._stopped:
                return None
            if self._executor is None:
                self._executor = ThreadPoolExecutor(
                    max_workers=1,
                    thread_name_prefix="rolling-thunder-preferences",
                )
            return self._executor

    def _write_map_zoom_safely(self, zoom: int) -> None:
        try:
            self._repository.write_map_zoom(zoom)
        except (StorageError, ValueError) as error:
            with self._lock:
                self._errors[OperatorPreferenceKey.MAP_ZOOM] = str(error)
            return

        with self._lock:
            self._errors.pop(OperatorPreferenceKey.MAP_ZOOM, None)

    def _write_callsign_info_safely(self, enabled: bool) -> None:
        try:
            self._repository.write_callsign_info_enabled(enabled)
        except (StorageError, ValueError) as error:
            with self._lock:
                self._errors[OperatorPreferenceKey.CALLSIGN_INFO_ENABLED] = str(error)
            return

        with self._lock:
            self._errors.pop(OperatorPreferenceKey.CALLSIGN_INFO_ENABLED, None)

    def _write_radar_image_safely(self, enabled: bool) -> None:
        try:
            self._repository.write_radar_image_enabled(enabled)
        except (StorageError, ValueError) as error:
            with self._lock:
                self._errors[OperatorPreferenceKey.RADAR_IMAGE_ENABLED] = str(error)
            return

        with self._lock:
            self._errors.pop(OperatorPreferenceKey.RADAR_IMAGE_ENABLED, None)
