"""Crash-conscious private MeshCore inbox with independent consumer cursors.

All dequeued frames are committed synchronously before another firmware dequeue
is requested. The firmware removes an item *before* responding, so power loss
between those two actions can lose that one item; no false exactly-once claim.
This service never opens serial or sends RF.
"""

from __future__ import annotations

import os
import sqlite3
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Mapping

from rolling_thunder.meshcore_public_intake_protocol import (
    VerifiedChannel,
    decode_verified_channel_text,
)

_MAX_MESSAGE_BYTES = 176
_DEFAULT_CAPACITY = 25_000
_DEFAULT_BYTES_LIMIT = 32 * 1024 * 1024
_SCHEMA_VERSION = 1


class MessageStream(StrEnum):
    """Privacy classifications; only attested channel text is public."""

    PUBLIC = "public"
    PRIVATE = "private"
    QUARANTINE = "quarantine"


class BrokerCapacityError(RuntimeError):
    """Stop firmware dequeue when storage cannot safely accept another frame."""


@dataclass(frozen=True, slots=True)
class BrokerMessage:
    """One durable message; private/quarantine payloads are opaque bytes."""

    message_id: int
    stream: MessageStream
    payload: str | bytes
    received_at: datetime
    channel_slot: int | None
    channel_name: str | None
    sender_claimed_at: datetime | None


def _secure_database_file(path: Path) -> None:
    """Create an owner-only SQLite file without following an existing symlink."""
    if path.parent.is_symlink():
        raise PermissionError("Broker directory must not be a symlink")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if stat.S_IMODE(path.parent.stat().st_mode) & 0o077:
        raise PermissionError("Broker directory must be owner-only")
    try:
        descriptor = os.open(
            path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600
        )
    except FileExistsError:
        if path.is_symlink() or not path.is_file():
            raise PermissionError("Broker database must be a regular file") from None
        if stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise PermissionError("Broker database must be owner-only") from None
    else:
        os.close(descriptor)


class MeshcoreMessageBroker:
    """Own a separate SQLite inbox; never touch the Phase-1 observation tables.

    Consumer permissions are injected by composition. Supplying a consumer name
    is NOT authorization when constructing the production service: that service
    must independently establish the caller identity before invoking peek/ack.
    """

    def __init__(
        self,
        path: Path,
        *,
        consumers: Mapping[str, frozenset[MessageStream]] | None = None,
        capacity: int = _DEFAULT_CAPACITY,
        maximum_bytes: int = _DEFAULT_BYTES_LIMIT,
    ) -> None:
        if capacity < 1 or maximum_bytes < 4096:
            raise ValueError("Invalid broker limits")
        self._path = path
        self._consumers = dict(consumers or {})
        self._capacity = capacity
        self._maximum_bytes = maximum_bytes
        for name, streams in self._consumers.items():
            if not name or len(name) > 64 or not streams or any(
                not isinstance(stream, MessageStream) for stream in streams
            ):
                raise ValueError("Invalid consumer permission configuration")
        _secure_database_file(path)
        with self._write_connection() as connection:
            tables = {
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            expected = {"broker_schema", "broker_messages", "broker_cursors"}
            if tables and tables != expected:
                raise ValueError("Unsupported or incomplete broker database")
            if not tables:
                connection.executescript(
                    """
                    CREATE TABLE broker_schema (
                        id INTEGER PRIMARY KEY CHECK (id=1),
                        version INTEGER NOT NULL
                    );
                    INSERT INTO broker_schema VALUES (1, 1);
                    CREATE TABLE broker_messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        stream TEXT NOT NULL CHECK (
                            stream IN ('public', 'private', 'quarantine')),
                        payload BLOB NOT NULL,
                        received_at_utc TEXT NOT NULL,
                        channel_slot INTEGER,
                        channel_name TEXT,
                        sender_claimed_at_utc TEXT,
                        CHECK(length(payload) BETWEEN 1 AND 176)
                    );
                    CREATE INDEX broker_stream_idx
                        ON broker_messages(stream, id);
                    CREATE TABLE broker_cursors (
                        consumer TEXT NOT NULL,
                        stream TEXT NOT NULL,
                        last_ack_id INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY(consumer, stream)
                    );
                    """
                )
            version = connection.execute(
                "SELECT version FROM broker_schema WHERE id=1"
            ).fetchone()
            if version != (_SCHEMA_VERSION,):
                raise ValueError("Unsupported broker schema version")
            if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise ValueError("Corrupt broker database")

    def _write_connection(self) -> sqlite3.Connection:
        """Use full synchronous transactions and secure-delete of old content."""
        connection = sqlite3.connect(self._path, timeout=2.0)
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA secure_delete=ON")
        return connection

    def can_accept(self) -> bool:
        """Preflight backpressure before sending the destructive dequeue opcode."""
        with self._write_connection() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM broker_messages"
            ).fetchone()
            pages = connection.execute("PRAGMA page_count").fetchone()
            page_size = connection.execute("PRAGMA page_size").fetchone()
            return (
                count is not None and pages is not None and page_size is not None
                and int(count[0]) < self._capacity
                and int(pages[0]) * int(page_size[0]) < self._maximum_bytes
            )

    def store(
        self,
        frame: bytes,
        *,
        received_at: datetime,
        verified_channels: Mapping[int, VerifiedChannel],
    ) -> int:
        """Commit one dequeued response, including private and unknown content.

        Unknown channel text is quarantined rather than announced as public.
        Firmware channel-info replies containing secrets must never enter here.
        """
        if (
            not frame or len(frame) > _MAX_MESSAGE_BYTES
            or received_at.tzinfo is None or received_at.utcoffset() is None
        ):
            raise ValueError("Invalid dequeued frame or timestamp")
        opcode = frame[0]
        if opcode in (0x12, 0x0A):
            raise ValueError("Channel secret/no-more marker is not a message")
        stream = MessageStream.QUARANTINE
        payload = frame
        slot: int | None = None
        channel_name: str | None = None
        claimed: str | None = None
        if opcode in (0x07, 0x10):
            stream = MessageStream.PRIVATE
        elif opcode in (0x08, 0x11):
            index = 4 if opcode == 0x11 else 1
            if len(frame) > index:
                channel = verified_channels.get(frame[index])
                if channel is not None:
                    decoded = decode_verified_channel_text(frame, channel)
                    if decoded is not None:
                        stream = MessageStream.PUBLIC
                        payload = decoded.text.encode("utf-8")
                        slot = channel.slot
                        channel_name = channel.name
                        claimed = decoded.claimed_at.isoformat()
        # Binary or future protocol frames are restricted even when they
        # happen to include text that looks like a public-channel message.
        with self._write_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            count = connection.execute(
                "SELECT COUNT(*) FROM broker_messages"
            ).fetchone()
            pages = connection.execute("PRAGMA page_count").fetchone()
            page_size = connection.execute("PRAGMA page_size").fetchone()
            if (
                count is None or pages is None or page_size is None
                or int(count[0]) >= self._capacity
                or int(pages[0]) * int(page_size[0]) >= self._maximum_bytes
            ):
                raise BrokerCapacityError("Broker storage full; stop dequeue")
            cursor = connection.execute(
                """INSERT INTO broker_messages (
                    stream, payload, received_at_utc, channel_slot,
                    channel_name, sender_claimed_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    stream.value, payload, received_at.astimezone(UTC).isoformat(),
                    slot, channel_name, claimed,
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("No broker message identifier")
            return cursor.lastrowid

    def _authorize(self, consumer: str, stream: MessageStream) -> None:
        if not isinstance(stream, MessageStream) or (
            stream not in self._consumers.get(consumer, frozenset())
        ):
            raise PermissionError("Consumer not authorized for stream")

    def peek(
        self, consumer: str, stream: MessageStream, *, limit: int = 25
    ) -> tuple[BrokerMessage, ...]:
        """Read without consuming; separate cursor for each consumer/stream."""
        self._authorize(consumer, stream)
        if not 1 <= limit <= 100:
            raise ValueError("Invalid delivery limit")
        with sqlite3.connect(
            f"file:{self._path}?mode=ro", uri=True, timeout=1.0
        ) as connection:
            connection.execute("PRAGMA query_only=ON")
            row = connection.execute(
                "SELECT last_ack_id FROM broker_cursors "
                "WHERE consumer=? AND stream=?", (consumer, stream.value)
            ).fetchone()
            since = int(row[0]) if row else 0
            rows = connection.execute(
                """SELECT id, payload, received_at_utc, channel_slot,
                          channel_name, sender_claimed_at_utc
                   FROM broker_messages
                   WHERE stream=? AND id>?
                   ORDER BY id LIMIT ?""",
                (stream.value, since, limit),
            ).fetchall()
        results: list[BrokerMessage] = []
        for message_id, payload, received, slot, name, claimed in rows:
            data = (
                bytes(payload).decode("utf-8", errors="strict")
                if stream == MessageStream.PUBLIC else bytes(payload)
            )
            results.append(BrokerMessage(
                int(message_id), stream, data, datetime.fromisoformat(received),
                slot, name, datetime.fromisoformat(claimed) if claimed else None,
            ))
        return tuple(results)

    def acknowledge(
        self, consumer: str, stream: MessageStream, message_id: int
    ) -> None:
        """Advance this consumer only; cannot acknowledge other streams."""
        self._authorize(consumer, stream)
        if message_id < 1:
            raise ValueError("Invalid message identifier")
        with self._write_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            present = connection.execute(
                "SELECT 1 FROM broker_messages WHERE id=? AND stream=?",
                (message_id, stream.value),
            ).fetchone()
            if present is None:
                raise ValueError("Acknowledgement does not match stream")
            connection.execute(
                """INSERT INTO broker_cursors(consumer, stream, last_ack_id)
                   VALUES (?, ?, ?)
                   ON CONFLICT(consumer, stream) DO UPDATE SET
                     last_ack_id=MAX(last_ack_id, excluded.last_ack_id)""",
                (consumer, stream.value, message_id),
            )

    def status(self) -> dict[str, int]:
        """Return counts only, without exposing private payload metadata."""
        with sqlite3.connect(
            f"file:{self._path}?mode=ro", uri=True, timeout=1.0
        ) as connection:
            counts = dict(connection.execute(
                "SELECT stream, COUNT(*) FROM broker_messages GROUP BY stream"
            ).fetchall())
        return {stream.value: int(counts.get(stream.value, 0)) for stream in MessageStream}
