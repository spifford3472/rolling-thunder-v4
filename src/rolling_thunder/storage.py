"""SQLite storage initialization and schema migration for Rolling Thunder."""

import sqlite3
from pathlib import Path
from typing import Final

CURRENT_SCHEMA_VERSION: Final = 1

_MIGRATIONS: Final[dict[int, tuple[str, ...]]] = {
    1: (
        """
        CREATE TABLE schema_metadata (
            singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
            schema_version INTEGER NOT NULL CHECK (schema_version >= 0),
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        INSERT INTO schema_metadata (
            singleton_id,
            schema_version
        )
        VALUES (1, 0)
        """,
    ),
}


class StorageError(Exception):
    """Raised when local application storage cannot be initialized."""


def _schema_metadata_exists(connection: sqlite3.Connection) -> bool:
    """Return whether the schema metadata table exists."""
    result = connection.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table'
          AND name = 'schema_metadata'
        """
    ).fetchone()

    return result is not None


def _read_schema_version(connection: sqlite3.Connection) -> int:
    """Read the database schema version, treating a new database as version zero."""
    if not _schema_metadata_exists(connection):
        return 0

    result = connection.execute(
        """
        SELECT schema_version
        FROM schema_metadata
        WHERE singleton_id = 1
        """
    ).fetchone()

    if result is None:
        raise StorageError(
            "Database schema metadata is missing its required version record."
        )

    version = result[0]

    if not isinstance(version, int) or version < 0:
        raise StorageError("Database schema metadata contains an invalid version.")

    return version


def _apply_migrations(
    connection: sqlite3.Connection,
    current_version: int,
) -> int:
    """Apply pending database migrations transactionally."""
    if current_version > CURRENT_SCHEMA_VERSION:
        raise StorageError(
            "Database schema version "
            f"{current_version} is newer than supported version "
            f"{CURRENT_SCHEMA_VERSION}."
        )

    for target_version in range(current_version + 1, CURRENT_SCHEMA_VERSION + 1):
        migration = _MIGRATIONS.get(target_version)

        if migration is None:
            raise StorageError(
                f"Database migration {target_version} is not available."
            )

        try:
            connection.execute("BEGIN")

            for statement in migration:
                connection.execute(statement)

            connection.execute(
                """
                UPDATE schema_metadata
                SET schema_version = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE singleton_id = 1
                """,
                (target_version,),
            )

            connection.commit()
        except sqlite3.Error:
            connection.rollback()
            raise

    return CURRENT_SCHEMA_VERSION


def initialize_database(database_path: Path) -> int:
    """Create, migrate, and validate the configured SQLite database."""
    try:
        database_path.parent.mkdir(parents=True, exist_ok=True)

        with sqlite3.connect(database_path) as connection:
            connection.execute("PRAGMA foreign_keys = ON")

            foreign_keys_enabled = connection.execute(
                "PRAGMA foreign_keys"
            ).fetchone()

            if foreign_keys_enabled != (1,):
                raise StorageError(
                    "SQLite foreign-key enforcement could not be enabled: "
                    f"{database_path}"
                )

            current_version = _read_schema_version(connection)
            return _apply_migrations(connection, current_version)
    except StorageError:
        raise
    except (OSError, sqlite3.Error) as error:
        raise StorageError(
            f"Database could not be initialized: {database_path}: {error}"
        ) from error
