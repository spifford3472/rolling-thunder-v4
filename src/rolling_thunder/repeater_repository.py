"""SQLite persistence for operator six-meter repeater Active overrides."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from rolling_thunder.repeater_domain import RepeaterIdentity
from rolling_thunder.storage import StorageError, initialize_database


class RepeaterActiveOverrideRepository:
    """Persist per-repeater operator Active choices by stable identity."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        initialize_database(database_path)

    def read(self, identity: RepeaterIdentity) -> bool | None:
        """Return one stored override, or None when source default should apply."""
        try:
            with sqlite3.connect(self._database_path) as connection:
                row = connection.execute(
                    """
                    SELECT active
                    FROM repeater_active_overrides
                    WHERE repeater_identity = ?
                    """,
                    (identity.stable_key,),
                ).fetchone()
        except sqlite3.Error as error:
            raise StorageError(
                "Repeater Active override could not be read: "
                f"{identity.stable_key}: {error}"
            ) from error

        if row is None:
            return None
        value = row[0]
        if value == 1:
            return True
        if value == 0:
            return False
        return None

    def read_all(self) -> dict[str, bool]:
        """Return all valid stored overrides keyed by serialized stable identity."""
        try:
            with sqlite3.connect(self._database_path) as connection:
                rows = connection.execute(
                    """
                    SELECT repeater_identity, active
                    FROM repeater_active_overrides
                    ORDER BY repeater_identity
                    """
                ).fetchall()
        except sqlite3.Error as error:
            raise StorageError(f"Repeater Active overrides could not be read: {error}") from error

        overrides: dict[str, bool] = {}
        for identity, active in rows:
            if isinstance(identity, str) and active in {0, 1}:
                overrides[identity] = bool(active)
        return overrides

    def write(self, identity: RepeaterIdentity, active: bool) -> None:
        """Persist or replace one explicit operator override atomically."""
        try:
            with sqlite3.connect(self._database_path) as connection:
                connection.execute(
                    """
                    INSERT INTO repeater_active_overrides (
                        repeater_identity,
                        active,
                        updated_at
                    )
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(repeater_identity) DO UPDATE SET
                        active = excluded.active,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (identity.stable_key, 1 if active else 0),
                )
                connection.commit()
        except sqlite3.Error as error:
            raise StorageError(
                "Repeater Active override could not be stored: "
                f"{identity.stable_key}: {error}"
            ) from error

    def clear(self, identity: RepeaterIdentity) -> None:
        """Remove one override so effective Active falls back to source data."""
        try:
            with sqlite3.connect(self._database_path) as connection:
                connection.execute(
                    """
                    DELETE FROM repeater_active_overrides
                    WHERE repeater_identity = ?
                    """,
                    (identity.stable_key,),
                )
                connection.commit()
        except sqlite3.Error as error:
            raise StorageError(
                "Repeater Active override could not be cleared: "
                f"{identity.stable_key}: {error}"
            ) from error
