"""Optional Forge-only snapshots of fully synchronized QSO objects."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import UUID

from rolling_thunder.domain import Contact


class ContactSnapshotError(RuntimeError):
    """Secondary contact snapshot failure."""


class ForgeContactSnapshotRepository:
    """Immutable contact snapshots; this store never controls primary logging."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        try:
            with sqlite3.connect(database_path, timeout=2) as db:
                db.execute(
                    "CREATE TABLE IF NOT EXISTS synchronized_contact_snapshots "
                    "(contact_id TEXT PRIMARY KEY, contact_json TEXT NOT NULL)"
                )
        except sqlite3.Error as error:
            raise ContactSnapshotError("Cannot initialize snapshots") from error

    def record(self, contact: Contact) -> None:
        key = str(contact.contact_id)
        payload = contact.model_dump_json()
        try:
            with sqlite3.connect(self._database_path, timeout=2) as db:
                db.execute(
                    "INSERT OR IGNORE INTO synchronized_contact_snapshots "
                    "(contact_id,contact_json) VALUES (?,?)",
                    (key, payload),
                )
                row = db.execute(
                    "SELECT contact_json FROM synchronized_contact_snapshots WHERE contact_id=?",
                    (key,),
                ).fetchone()
                if row is None or row[0] != payload:
                    raise ContactSnapshotError("Snapshot UUID conflict")
        except sqlite3.Error as error:
            raise ContactSnapshotError("Cannot persist snapshot") from error

    def read(self, contact_id: UUID) -> Contact | None:
        try:
            with sqlite3.connect(f"file:{self._database_path.resolve()}?mode=ro", uri=True) as db:
                row = db.execute(
                    "SELECT contact_json FROM synchronized_contact_snapshots WHERE contact_id=?",
                    (str(contact_id),),
                ).fetchone()
        except sqlite3.Error as error:
            raise ContactSnapshotError("Cannot read snapshot") from error
        return None if row is None else Contact.model_validate_json(row[0])
