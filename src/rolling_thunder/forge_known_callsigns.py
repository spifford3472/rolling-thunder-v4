"""Durable Forge-owned known-callsign repository; comments remain private."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from rolling_thunder.known_callsigns import (
    MAX_KNOWN_CALLSIGNS,
    KnownCallsignBatch,
    KnownCallsignInput,
    KnownCallsignLookup,
    KnownCallsignSnapshot,
    KnownCallsignStatus,
    normalize_known_callsign,
)


@dataclass(frozen=True, slots=True)
class KnownCallsignRecord:
    data: KnownCallsignInput
    created_at: str
    updated_at: str


class ForgeKnownCallsignRepository:
    """Short transaction/connection per operation, safe for HTTP worker threads."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise ValueError("Unsupported known-callsign database schema")
            connection.execute("""CREATE TABLE IF NOT EXISTS known_callsigns (
                callsign TEXT PRIMARY KEY COLLATE NOCASE,
                display_name TEXT NOT NULL,
                comment TEXT NOT NULL,
                active INTEGER NOT NULL CHECK(active IN (0, 1)),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )""")
            connection.execute("PRAGMA user_version = 1")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def list_records(self) -> tuple[KnownCallsignRecord, ...]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM known_callsigns ORDER BY callsign").fetchall()
        return tuple(self._record(row) for row in rows)

    def save(self, data: KnownCallsignInput, *, original: str | None = None) -> None:
        """Create or explicitly edit; collisions never overwrite another record."""
        data = KnownCallsignInput.model_validate(data.model_dump())
        timestamp = datetime.now(UTC).isoformat()
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                if original is None:
                    count = connection.execute("SELECT COUNT(*) FROM known_callsigns").fetchone()[0]
                    if count >= MAX_KNOWN_CALLSIGNS:
                        raise ValueError("Known-callsign directory is full")
                    connection.execute(
                        "INSERT INTO known_callsigns VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            data.callsign,
                            data.display_name,
                            data.comment,
                            int(data.active),
                            timestamp,
                            timestamp,
                        ),
                    )
                else:
                    cursor = connection.execute(
                        """UPDATE known_callsigns SET callsign=?, display_name=?, comment=?,
                        active=?, updated_at=? WHERE callsign=?""",
                        (
                            data.callsign,
                            data.display_name,
                            data.comment,
                            int(data.active),
                            timestamp,
                            normalize_known_callsign(original),
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise ValueError("Known callsign does not exist")
        except sqlite3.IntegrityError as error:
            raise ValueError("Callsign already exists") from error

    def delete(self, callsign: str) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM known_callsigns WHERE callsign=?",
                (normalize_known_callsign(callsign),),
            )
            if cursor.rowcount != 1:
                raise ValueError("Known callsign does not exist")

    def snapshot(self) -> KnownCallsignSnapshot:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT callsign FROM known_callsigns WHERE active=1 ORDER BY callsign"
            ).fetchall()
        return KnownCallsignSnapshot(
            entries=tuple(
                KnownCallsignStatus(callsign=row[0], known=True, relationship="friend")
                for row in rows
            )
        )

    def lookup(self, request: KnownCallsignBatch) -> KnownCallsignLookup:
        active = {entry.callsign for entry in self.snapshot().entries}
        return KnownCallsignLookup(
            results=tuple(
                KnownCallsignStatus(
                    callsign=call,
                    known=call in active,
                    relationship="friend" if call in active else None,
                )
                for call in dict.fromkeys(request.callsigns)
            )
        )

    @staticmethod
    def _record(row: sqlite3.Row) -> KnownCallsignRecord:
        return KnownCallsignRecord(
            KnownCallsignInput(
                callsign=row["callsign"],
                display_name=row["display_name"],
                comment=row["comment"],
                active=bool(row["active"]),
            ),
            row["created_at"],
            row["updated_at"],
        )
