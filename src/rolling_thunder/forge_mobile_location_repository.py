"""Transactional SQLite persistence for the latest accepted Forge mobile location."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from pydantic import ValidationError

from rolling_thunder.forge_mobile_location import (
    ForgeMobileLocationStorageError,
    MobileLocationRecord,
    MobileLocationState,
    StaleMobileLocationError,
)

_MOBILE_LOCATION_SCHEMA_VERSION: Final = 1
_MAX_ERROR_LENGTH: Final = 500


class SqliteForgeMobileLocationRepository:
    """Store one latest mobile-location record in the existing Forge SQLite file."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._initialize()

    def load(self) -> MobileLocationState | None:
        """Load and revalidate the singleton retained location, when present."""
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT
                        revision,
                        latitude,
                        longitude,
                        fix_at,
                        received_at,
                        speed_m_s,
                        heading_degrees
                    FROM forge_mobile_location
                    WHERE singleton_id = 1
                    """
                ).fetchone()
        except sqlite3.Error as error:
            raise ForgeMobileLocationStorageError(
                f"Forge mobile-location database could not be read: "
                f"{self._database_path}: {self._bounded_error(error)}"
            ) from error

        if row is None:
            return None

        try:
            location = self._location_from_row(row)
            revision = self._require_int(row["revision"], "revision")
            return MobileLocationState(revision=revision, location=location)
        except (KeyError, TypeError, ValueError, ValidationError) as error:
            raise ForgeMobileLocationStorageError(
                f"Forge mobile-location database contains invalid data: "
                f"{self._database_path}: {self._bounded_error(error)}"
            ) from error

    def replace(self, location: MobileLocationRecord) -> MobileLocationState:
        """Persist a strictly newer location atomically and return its revision."""
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                current = connection.execute(
                    """
                    SELECT revision, fix_at, received_at
                    FROM forge_mobile_location
                    WHERE singleton_id = 1
                    """
                ).fetchone()

                if current is None:
                    revision = 1
                else:
                    current_fix_at = self._parse_timestamp(current["fix_at"])
                    current_received_at = self._parse_timestamp(current["received_at"])
                    if (
                        location.fix_at <= current_fix_at
                        or location.received_at <= current_received_at
                    ):
                        raise StaleMobileLocationError(
                            "mobile location must advance both fix_at and received_at"
                        )
                    revision = self._require_int(current["revision"], "revision") + 1

                connection.execute(
                    """
                    INSERT INTO forge_mobile_location (
                        singleton_id,
                        revision,
                        latitude,
                        longitude,
                        fix_at,
                        received_at,
                        speed_m_s,
                        heading_degrees
                    )
                    VALUES (1, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(singleton_id) DO UPDATE SET
                        revision = excluded.revision,
                        latitude = excluded.latitude,
                        longitude = excluded.longitude,
                        fix_at = excluded.fix_at,
                        received_at = excluded.received_at,
                        speed_m_s = excluded.speed_m_s,
                        heading_degrees = excluded.heading_degrees
                    """,
                    (
                        revision,
                        location.latitude,
                        location.longitude,
                        self._timestamp_text(location.fix_at),
                        self._timestamp_text(location.received_at),
                        location.speed_m_s,
                        location.heading_degrees,
                    ),
                )
                connection.commit()
        except StaleMobileLocationError:
            raise
        except (sqlite3.Error, TypeError, ValueError) as error:
            raise ForgeMobileLocationStorageError(
                f"Forge mobile-location database could not be replaced: "
                f"{self._database_path}: {self._bounded_error(error)}"
            ) from error

        return MobileLocationState(revision=revision, location=location)

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
                    raise ForgeMobileLocationStorageError(
                        "Refusing to initialize Forge mobile location in a Rolling Thunder "
                        "application database. Configure a separate Forge database path."
                    )

                connection.execute("BEGIN")
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS forge_mobile_location_schema_metadata (
                        singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                        schema_version INTEGER NOT NULL CHECK (schema_version >= 1)
                    )
                    """
                )
                version_row = connection.execute(
                    """
                    SELECT schema_version
                    FROM forge_mobile_location_schema_metadata
                    WHERE singleton_id = 1
                    """
                ).fetchone()
                if version_row is None:
                    connection.execute(
                        """
                        INSERT INTO forge_mobile_location_schema_metadata (
                            singleton_id,
                            schema_version
                        )
                        VALUES (1, ?)
                        """,
                        (_MOBILE_LOCATION_SCHEMA_VERSION,),
                    )
                elif version_row[0] != _MOBILE_LOCATION_SCHEMA_VERSION:
                    raise ForgeMobileLocationStorageError(
                        "Unsupported Forge mobile-location schema version: "
                        f"{version_row[0]!r}; expected {_MOBILE_LOCATION_SCHEMA_VERSION}."
                    )

                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS forge_mobile_location (
                        singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                        revision INTEGER NOT NULL CHECK (revision >= 1),
                        latitude REAL NOT NULL CHECK (latitude >= -90 AND latitude <= 90),
                        longitude REAL NOT NULL CHECK (longitude >= -180 AND longitude <= 180),
                        fix_at TEXT NOT NULL,
                        received_at TEXT NOT NULL,
                        speed_m_s REAL CHECK (
                            speed_m_s IS NULL OR (speed_m_s >= 0 AND speed_m_s <= 100)
                        ),
                        heading_degrees REAL CHECK (
                            heading_degrees IS NULL
                            OR (heading_degrees >= 0 AND heading_degrees < 360)
                        )
                    )
                    """
                )
                connection.commit()
        except ForgeMobileLocationStorageError:
            raise
        except (OSError, sqlite3.Error) as error:
            raise ForgeMobileLocationStorageError(
                f"Forge mobile-location database could not be initialized: "
                f"{self._database_path}: {self._bounded_error(error)}"
            ) from error

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        return connection

    @classmethod
    def _location_from_row(cls, row: sqlite3.Row) -> MobileLocationRecord:
        return MobileLocationRecord(
            latitude=cls._require_float(row["latitude"], "latitude"),
            longitude=cls._require_float(row["longitude"], "longitude"),
            fix_at=cls._parse_timestamp(row["fix_at"]),
            received_at=cls._parse_timestamp(row["received_at"]),
            speed_m_s=cls._optional_float(row["speed_m_s"], "speed_m_s"),
            heading_degrees=cls._optional_float(
                row["heading_degrees"], "heading_degrees"
            ),
        )

    @staticmethod
    def _timestamp_text(value: datetime) -> str:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Forge mobile-location timestamps must be timezone-aware")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")

    @classmethod
    def _parse_timestamp(cls, value: object) -> datetime:
        if not isinstance(value, str):
            raise TypeError("stored timestamp must be text")
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("stored Forge mobile-location timestamp must include timezone")
        return parsed.astimezone(UTC)

    @staticmethod
    def _require_int(value: object, field_name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{field_name} must be an integer")
        return value

    @staticmethod
    def _require_float(value: object, field_name: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"{field_name} must be numeric")
        return float(value)

    @classmethod
    def _optional_float(cls, value: object, field_name: str) -> float | None:
        if value is None:
            return None
        return cls._require_float(value, field_name)

    @staticmethod
    def _bounded_error(error: BaseException) -> str:
        text = str(error).strip() or error.__class__.__name__
        return text[:_MAX_ERROR_LENGTH]
