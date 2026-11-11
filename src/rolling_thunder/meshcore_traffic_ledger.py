"""Isolated durable MeshCore public-message processing ledger.

The broker owns raw messages and consumer cursors. This *separate* database
records a public message's analysis before a downstream consumer can ACK it.
No private frames, raw radio data, RF actions or UI work enter this module.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path

from rolling_thunder.meshcore_public_consumer import PublicBrokerMessage
from rolling_thunder.meshcore_public_intelligence import (
    TrafficChannelSelection,
    classify_traffic_snapshot,
)

_SCHEMA_VERSION = 1
_MAX_RECORDS = 250_000


class TrafficLedgerError(RuntimeError):
    """Fail closed on storage limits, conflicts or invalid local authority."""


class TrafficDisposition(StrEnum):
    """Each stored public message has exactly one analysis disposition."""

    CANDIDATE = "candidate"
    DUPLICATE = "duplicate"
    IGNORED = "ignored"


@dataclass(frozen=True, slots=True)
class TrafficRecord:
    """Stable persisted processing result; no speculative hazard assertion."""

    broker_message_id: int
    disposition: TrafficDisposition
    event_fingerprint: str | None
    category: str | None


def _secure_store(path: Path) -> None:
    """Create an owner-only database; refuse unsafe links and permissions."""
    if path.parent.is_symlink():
        raise TrafficLedgerError("Traffic ledger directory must not be a symlink")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if stat.S_IMODE(path.parent.stat().st_mode) & 0o077:
        raise TrafficLedgerError("Traffic ledger directory is not private")
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file():
            raise TrafficLedgerError("Traffic ledger must be a regular file")
        if path.stat().st_uid != os.geteuid() or (
            stat.S_IMODE(path.stat().st_mode) & 0o077
        ):
            raise TrafficLedgerError("Traffic ledger permissions are unsafe")
        return
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    os.close(fd)


class TrafficLedger:
    """One separate schema-1 SQLite ledger, never the broker or QSO store."""

    def __init__(
        self,
        path: Path,
        *,
        approved: TrafficChannelSelection,
        duplicate_window: timedelta = timedelta(minutes=30),
        max_records: int = _MAX_RECORDS,
    ) -> None:
        if not timedelta(seconds=1) <= duplicate_window <= timedelta(days=1):
            raise ValueError("Invalid traffic duplicate window")
        if not 1 <= max_records <= _MAX_RECORDS:
            raise ValueError("Invalid traffic ledger capacity")
        _secure_store(path)
        self._path = path
        self._approved = approved
        self._duplicate_window = duplicate_window
        self._max_records = max_records
        with self._connection() as connection:
            tables = {
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%'"
                )
            }
            allowed = {"traffic_schema", "traffic_records"}
            if tables and tables != allowed:
                raise TrafficLedgerError("Unsupported traffic ledger tables")
            if not tables:
                connection.executescript(
                    """
                    CREATE TABLE traffic_schema(
                        id INTEGER PRIMARY KEY CHECK(id=1),
                        version INTEGER NOT NULL
                    );
                    INSERT INTO traffic_schema VALUES (1, 1);
                    CREATE TABLE traffic_records(
                        broker_message_id INTEGER PRIMARY KEY CHECK(broker_message_id>0),
                        message_sha256 TEXT NOT NULL,
                        received_at_utc TEXT NOT NULL,
                        channel_slot INTEGER NOT NULL,
                        channel_name TEXT NOT NULL,
                        disposition TEXT NOT NULL CHECK(disposition IN (
                            'candidate', 'duplicate', 'ignored'
                        )),
                        event_fingerprint TEXT,
                        category TEXT,
                        road TEXT,
                        travel_direction TEXT,
                        exit_label TEXT,
                        CHECK (
                            (disposition='ignored' AND event_fingerprint IS NULL
                                AND category IS NULL)
                            OR (disposition!='ignored' AND event_fingerprint IS NOT NULL
                                AND category IS NOT NULL)
                        )
                    );
                    CREATE INDEX traffic_dedupe_idx
                        ON traffic_records(event_fingerprint, received_at_utc);
                    """
                )
            version = connection.execute(
                "SELECT version FROM traffic_schema WHERE id=1"
            ).fetchone()
            if version != (_SCHEMA_VERSION,):
                raise TrafficLedgerError("Unsupported traffic ledger version")
            if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise TrafficLedgerError("Traffic ledger corrupt")

    def _connection(self) -> sqlite3.Connection:
        """Synchronous commits prevent ACK ahead of durable local processing."""
        connection = sqlite3.connect(self._path, timeout=2.0)
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA secure_delete=ON")
        return connection

    def process(self, message: PublicBrokerMessage) -> TrafficRecord:
        """Classify and commit idempotently; no network and no ACK in this call."""
        if (
            type(message.message_id) is not int or message.message_id < 1
            or message.received_at.utcoffset() is None
            or len(message.text) > 512
            or not message.text.strip()
        ):
            raise TrafficLedgerError("Invalid broker message")
        # Hash all relevant attributes, so replaying a changed broker ID
        # cannot silently rewrite previously acknowledged processing.
        canonical = json.dumps(
            [
                message.channel_slot, message.channel_name, message.text,
                message.received_at.astimezone(UTC).isoformat(),
            ],
            separators=(",", ":"),
            ensure_ascii=False,
        )
        message_sha = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        incidents = classify_traffic_snapshot((message,), self._approved)
        incident = incidents[0].incident if incidents else None
        fingerprint: str | None = None
        if incident is not None:
            normalized = " ".join(message.text.casefold().split())
            source = json.dumps(
                [message.channel_slot, message.channel_name, normalized],
                separators=(",", ":"),
                ensure_ascii=False,
            )
            fingerprint = hashlib.sha256(source.encode("utf-8")).hexdigest()

        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT message_sha256, disposition, event_fingerprint, category "
                "FROM traffic_records WHERE broker_message_id=?",
                (message.message_id,),
            ).fetchone()
            if existing is not None:
                if existing[0] != message_sha:
                    raise TrafficLedgerError("Broker ID content changed on replay")
                return TrafficRecord(
                    message.message_id, TrafficDisposition(existing[1]),
                    existing[2], existing[3],
                )

            count = connection.execute(
                "SELECT COUNT(*) FROM traffic_records"
            ).fetchone()
            if count is None or int(count[0]) >= self._max_records:
                raise TrafficLedgerError("Traffic ledger full; cannot ACK")
            disposition = TrafficDisposition.IGNORED
            if incident is not None:
                assert fingerprint is not None
                cutoff = (
                    message.received_at.astimezone(UTC) - self._duplicate_window
                ).isoformat()
                current_time = message.received_at.astimezone(UTC).isoformat()
                prior = connection.execute(
                    "SELECT 1 FROM traffic_records "
                    "WHERE event_fingerprint=? AND received_at_utc>=? "
                    "AND received_at_utc<=? LIMIT 1",
                    (fingerprint, cutoff, current_time),
                ).fetchone()
                disposition = (
                    TrafficDisposition.DUPLICATE if prior is not None
                    else TrafficDisposition.CANDIDATE
                )
            connection.execute(
                """INSERT INTO traffic_records(
                    broker_message_id, message_sha256, received_at_utc,
                    channel_slot, channel_name, disposition,
                    event_fingerprint, category, road, travel_direction,
                    exit_label
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    message.message_id, message_sha,
                    message.received_at.astimezone(UTC).isoformat(),
                    message.channel_slot, message.channel_name, disposition.value,
                    fingerprint, incident.category.value if incident else None,
                    incident.road if incident else None,
                    incident.travel_direction if incident else None,
                    incident.exit if incident else None,
                ),
            )
        return TrafficRecord(
            message.message_id, disposition, fingerprint,
            incident.category.value if incident else None,
        )

    def counts(self) -> dict[str, int]:
        """Expose only per-disposition counters; no raw message content."""
        with sqlite3.connect(
            f"file:{self._path}?mode=ro", uri=True, timeout=1.0
        ) as connection:
            rows = connection.execute(
                "SELECT disposition, COUNT(*) FROM traffic_records "
                "GROUP BY disposition"
            ).fetchall()
        data = dict(rows)
        return {value.value: int(data.get(value.value, 0)) for value in TrafficDisposition}
