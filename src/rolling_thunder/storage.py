"""SQLite storage initialization for Rolling Thunder."""

import sqlite3
from pathlib import Path


class StorageError(Exception):
    """Raised when local application storage cannot be initialized."""


def initialize_database(database_path: Path) -> None:
    """Create and validate the configured SQLite database."""
    try:
        database_path.parent.mkdir(parents=True, exist_ok=True)

        with sqlite3.connect(database_path) as connection:
            connection.execute("PRAGMA foreign_keys = ON")

            foreign_keys_enabled = connection.execute(
                "PRAGMA foreign_keys"
            ).fetchone()

            if foreign_keys_enabled != (1,):
                raise StorageError(
                    f"SQLite foreign-key enforcement could not be enabled: "
                    f"{database_path}"
                )
    except StorageError:
        raise
    except (OSError, sqlite3.Error) as error:
        raise StorageError(
            f"Database could not be initialized: {database_path}: {error}"
        ) from error
