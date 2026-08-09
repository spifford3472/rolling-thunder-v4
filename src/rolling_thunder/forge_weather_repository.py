"""Transactional SQLite persistence for retained Forge weather snapshots."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Final

from pydantic import ValidationError

from rolling_thunder.forge_weather import (
    ForgeWeatherState,
    ForgeWeatherStorageError,
    WeatherProviderStatus,
    WeatherSnapshot,
)

_WEATHER_SCHEMA_VERSION: Final = 1
_MAX_ERROR_LENGTH: Final = 500


class SqliteForgeWeatherRepository:
    """Store one complete retained weather snapshot in the Forge SQLite file."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._initialize()

    def load(self) -> ForgeWeatherState | None:
        """Load and revalidate the singleton retained weather snapshot."""
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT revision, snapshot_json
                    FROM forge_weather_snapshot
                    WHERE singleton_id = 1
                    """
                ).fetchone()
        except sqlite3.Error as error:
            raise ForgeWeatherStorageError(
                "Forge weather database could not be read: "
                f"{self._database_path}: {self._bounded_error(error)}"
            ) from error

        if row is None:
            return None

        try:
            revision = self._require_int(row["revision"], "revision")
            snapshot_json = row["snapshot_json"]
            if not isinstance(snapshot_json, str):
                raise TypeError("snapshot_json must be text")
            snapshot = WeatherSnapshot.model_validate_json(snapshot_json)
            return ForgeWeatherState(
                revision=revision,
                snapshot=snapshot,
                provider_status=WeatherProviderStatus.STARTING,
            )
        except (KeyError, TypeError, ValueError, ValidationError) as error:
            raise ForgeWeatherStorageError(
                "Forge weather database contains invalid data: "
                f"{self._database_path}: {self._bounded_error(error)}"
            ) from error

    def replace(self, snapshot: WeatherSnapshot) -> ForgeWeatherState:
        """Transactionally replace the retained snapshot and advance revision."""
        snapshot_json = snapshot.model_dump_json()
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    """
                    SELECT revision
                    FROM forge_weather_snapshot
                    WHERE singleton_id = 1
                    """
                ).fetchone()
                revision = (
                    1
                    if row is None
                    else self._require_int(row["revision"], "revision") + 1
                )
                connection.execute(
                    """
                    INSERT INTO forge_weather_snapshot (
                        singleton_id,
                        revision,
                        snapshot_json
                    )
                    VALUES (1, ?, ?)
                    ON CONFLICT(singleton_id) DO UPDATE SET
                        revision = excluded.revision,
                        snapshot_json = excluded.snapshot_json
                    """,
                    (revision, snapshot_json),
                )
                connection.commit()
        except (sqlite3.Error, TypeError, ValueError) as error:
            raise ForgeWeatherStorageError(
                "Forge weather database could not be replaced: "
                f"{self._database_path}: {self._bounded_error(error)}"
            ) from error

        return ForgeWeatherState(
            revision=revision,
            snapshot=snapshot,
            provider_status=WeatherProviderStatus.STARTING,
        )

    def _initialize(self) -> None:
        try:
            self._database_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                existing_tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
                if (
                    "forge_schema_metadata" not in existing_tables
                    and {"schema_metadata", "contacts"} & existing_tables
                ):
                    raise ForgeWeatherStorageError(
                        "Refusing to initialize Forge weather in a Rolling Thunder "
                        "application database. Configure a separate Forge database path."
                    )

                connection.execute("BEGIN")
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS forge_weather_schema_metadata (
                        singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                        schema_version INTEGER NOT NULL CHECK (schema_version >= 1)
                    )
                    """
                )
                version_row = connection.execute(
                    """
                    SELECT schema_version
                    FROM forge_weather_schema_metadata
                    WHERE singleton_id = 1
                    """
                ).fetchone()
                if version_row is None:
                    connection.execute(
                        """
                        INSERT INTO forge_weather_schema_metadata (
                            singleton_id,
                            schema_version
                        )
                        VALUES (1, ?)
                        """,
                        (_WEATHER_SCHEMA_VERSION,),
                    )
                elif version_row[0] != _WEATHER_SCHEMA_VERSION:
                    raise ForgeWeatherStorageError(
                        "Unsupported Forge weather schema version: "
                        f"{version_row[0]!r}; expected {_WEATHER_SCHEMA_VERSION}."
                    )

                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS forge_weather_snapshot (
                        singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                        revision INTEGER NOT NULL CHECK (revision >= 1),
                        snapshot_json TEXT NOT NULL
                    )
                    """
                )
                connection.commit()
        except ForgeWeatherStorageError:
            raise
        except (OSError, sqlite3.Error) as error:
            raise ForgeWeatherStorageError(
                "Forge weather database could not be initialized: "
                f"{self._database_path}: {self._bounded_error(error)}"
            ) from error

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _require_int(value: object, field_name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{field_name} must be an integer")
        return value

    @staticmethod
    def _bounded_error(error: BaseException) -> str:
        text = str(error).strip() or error.__class__.__name__
        return text[:_MAX_ERROR_LENGTH]
