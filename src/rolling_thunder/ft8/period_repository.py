"""Append-only local archive of individually keyed FT8 periods.

This store is independent of the terminal-attempt upload and makes no claim
that a configured CAT power is measured RF output power.
"""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID

from rolling_thunder.ft8.hardware_transmit import FT8TransmitPeriodTelemetry


class FT8TransmitPeriodRepository:
    def __init__(self, path: Path) -> None:
        self._path = path
        with sqlite3.connect(path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS ft8_transmit_period (
                qso_id TEXT NOT NULL,
                emission_index INTEGER NOT NULL,
                started_at_utc TEXT NOT NULL,
                ended_at_utc TEXT NOT NULL,
                configured_power_watts INTEGER,
                power_readback_verified INTEGER NOT NULL CHECK(power_readback_verified IN (0,1)),
                frequency_hz INTEGER NOT NULL,
                transmitted INTEGER NOT NULL CHECK(transmitted IN (0,1)),
                PRIMARY KEY(qso_id, emission_index)
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS ft8_transmit_intent (
                intent_id TEXT PRIMARY KEY, qso_id TEXT NOT NULL,
                created_at_utc TEXT NOT NULL, frequency_hz INTEGER NOT NULL,
                configured_power_watts INTEGER,
                state TEXT NOT NULL CHECK(state IN ('uncertain','completed'))
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS ft8_transmit_period_delivery (
                qso_id TEXT NOT NULL, emission_index INTEGER NOT NULL,
                synchronized_at_utc TEXT NOT NULL,
                PRIMARY KEY (qso_id, emission_index),
                FOREIGN KEY(qso_id,emission_index) REFERENCES ft8_transmit_period(qso_id,emission_index)
            )""")
            if not any(row[1] == "transmit_audio_offset_hz" for row in db.execute("PRAGMA table_info(ft8_transmit_period)")):
                db.execute("ALTER TABLE ft8_transmit_period ADD COLUMN transmit_audio_offset_hz INTEGER")
            db.execute("CREATE INDEX IF NOT EXISTS idx_ft8_transmit_period_time ON ft8_transmit_period(started_at_utc, frequency_hz)")

    def begin_intent(self, intent_id: UUID, qso_id: UUID, frequency_hz: int,
                     configured_power_watts: int | None) -> None:
        """Durably register an uncertain attempt before PTT is keyed."""
        if frequency_hz <= 0:
            raise ValueError("frequency must be positive")
        with sqlite3.connect(self._path) as db:
            db.execute("INSERT INTO ft8_transmit_intent VALUES (?,?,?,?,?,'uncertain')",
                       (str(intent_id), str(qso_id), datetime.now(UTC).isoformat(),
                        frequency_hz, configured_power_watts))

    def finish_intent(self, intent_id: UUID) -> None:
        with sqlite3.connect(self._path) as db:
            cursor = db.execute("UPDATE ft8_transmit_intent SET state='completed' "
                                "WHERE intent_id=? AND state='uncertain'",(str(intent_id),))
            if cursor.rowcount != 1:
                raise ValueError("intent not found or already completed")

    def complete_intent(self, intent_id: UUID, record: FT8TransmitPeriodTelemetry) -> None:
        """Atomically write one emission and complete its matching pre-key intent."""
        self._validate_record(record)
        with sqlite3.connect(self._path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT qso_id,frequency_hz,configured_power_watts,state "
                "FROM ft8_transmit_intent WHERE intent_id=?", (str(intent_id),)
            ).fetchone()
            if row is None:
                raise ValueError("unknown transmission intent")
            qso, frequency, power, state = row
            if qso != str(record.qso_id) or frequency != record.frequency_hz or power != record.configured_power_watts:
                raise ValueError("transmission does not match its immutable intent")
            if state != "uncertain":
                raise ValueError("transmission intent already completed")
            index = db.execute(
                "SELECT COALESCE(MAX(emission_index),0)+1 FROM ft8_transmit_period WHERE qso_id=?",
                (qso,),
            ).fetchone()[0]
            db.execute("INSERT INTO ft8_transmit_period (qso_id,emission_index,started_at_utc,ended_at_utc,configured_power_watts,power_readback_verified,frequency_hz,transmitted,transmit_audio_offset_hz) VALUES (?,?,?,?,?,?,?,?,?)", (
                qso, index, record.started_at_utc.astimezone(UTC).isoformat(),
                record.ended_at_utc.astimezone(UTC).isoformat(),
                record.configured_power_watts, int(record.power_readback_verified),
                record.frequency_hz, int(record.transmitted), record.transmit_audio_offset_hz,
            ))
            db.execute("UPDATE ft8_transmit_intent SET state='completed' WHERE intent_id=?", (str(intent_id),))

    @staticmethod
    def _validate_record(record: FT8TransmitPeriodTelemetry) -> None:
        if record.started_at_utc.tzinfo is None or record.ended_at_utc.tzinfo is None:
            raise ValueError("transmission timestamps require timezones")
        if record.ended_at_utc < record.started_at_utc:
            raise ValueError("transmission end precedes start")
        if record.transmit_audio_offset_hz is not None and not 200 <= record.transmit_audio_offset_hz <= 3500:
            raise ValueError("invalid transmit audio offset")
        if record.power_readback_verified != (record.configured_power_watts is not None):
            raise ValueError("CAT power provenance must match recorded setting")

    def uncertain_intents(self) -> tuple[UUID, ...]:
        with sqlite3.connect(self._path) as db:
            rows=db.execute("SELECT intent_id FROM ft8_transmit_intent WHERE state='uncertain'").fetchall()
        return tuple(UUID(row[0]) for row in rows)

    def append(self, record: FT8TransmitPeriodTelemetry) -> None:
        self._validate_record(record)
        with sqlite3.connect(self._path) as db:
            db.execute("BEGIN IMMEDIATE")
            index = db.execute(
                "SELECT COALESCE(MAX(emission_index),0)+1 FROM ft8_transmit_period WHERE qso_id=?",
                (str(record.qso_id),),
            ).fetchone()[0]
            db.execute("""INSERT INTO ft8_transmit_period (qso_id,emission_index,started_at_utc,ended_at_utc,configured_power_watts,power_readback_verified,frequency_hz,transmitted,transmit_audio_offset_hz) VALUES (?,?,?,?,?,?,?,?,?)""", (
                str(record.qso_id), index,
                record.started_at_utc.astimezone(UTC).isoformat(),
                record.ended_at_utc.astimezone(UTC).isoformat(),
                record.configured_power_watts, int(record.power_readback_verified),
                record.frequency_hz, int(record.transmitted), record.transmit_audio_offset_hz,
            ))

    def for_qso(self, qso_id: UUID) -> tuple[FT8TransmitPeriodTelemetry, ...]:
        with sqlite3.connect(self._path) as db:
            rows=db.execute("""SELECT started_at_utc,ended_at_utc,configured_power_watts,
                     power_readback_verified,frequency_hz,transmitted,transmit_audio_offset_hz
                     FROM ft8_transmit_period WHERE qso_id=? ORDER BY emission_index""",
                     (str(qso_id),)).fetchall()
        return tuple(FT8TransmitPeriodTelemetry(
            qso_id, datetime.fromisoformat(start),datetime.fromisoformat(end),
            power,bool(verified),freq,bool(transmitted),offset
        ) for start,end,power,verified,freq,transmitted,offset in rows)

    def pending(self, *, limit: int = 50) -> tuple[tuple[UUID, int, FT8TransmitPeriodTelemetry], ...]:
        """Read unacknowledged periods in stable order; never delete source evidence."""
        if not 1 <= limit <= 500:
            raise ValueError("limit out of bounds")
        with sqlite3.connect(self._path) as db:
            rows = db.execute("""SELECT p.qso_id,p.emission_index,p.started_at_utc,
                p.ended_at_utc,p.configured_power_watts,p.power_readback_verified,
                p.frequency_hz,p.transmitted,p.transmit_audio_offset_hz
                FROM ft8_transmit_period p LEFT JOIN ft8_transmit_period_delivery d
                  ON p.qso_id=d.qso_id AND p.emission_index=d.emission_index
                WHERE d.qso_id IS NULL
                ORDER BY p.started_at_utc,p.qso_id,p.emission_index LIMIT ?""",(limit,)).fetchall()
        return tuple((UUID(qso),idx,FT8TransmitPeriodTelemetry(
            UUID(qso),datetime.fromisoformat(start),datetime.fromisoformat(end),
            power,bool(verified),frequency,bool(transmitted),offset))
            for qso,idx,start,end,power,verified,frequency,transmitted,offset in rows)

    def acknowledge(self, qso_id: UUID, emission_index: int) -> None:
        """Only call after Forge confirms durable acceptance or identical replay."""
        with sqlite3.connect(self._path) as db:
            db.execute("BEGIN IMMEDIATE")
            exists=db.execute(
                "SELECT 1 FROM ft8_transmit_period WHERE qso_id=? AND emission_index=?",
                (str(qso_id), emission_index)).fetchone()
            if exists is None:
                raise ValueError("cannot acknowledge missing emission")
            db.execute("""INSERT OR IGNORE INTO ft8_transmit_period_delivery
                VALUES (?,?,?)""",(str(qso_id),emission_index,datetime.now(UTC).isoformat()))



class FT8PeriodUploadClient(Protocol):
    def upload_ft8_period(
        self, qso_id: UUID, emission_index: int, record: FT8TransmitPeriodTelemetry
    ) -> None: ...


class FT8PeriodSyncService:
    """Retry pending emissions without deleting local records or forging acks."""

    def __init__(self, repository: FT8TransmitPeriodRepository, client: FT8PeriodUploadClient) -> None:
        self._repository = repository
        self._client = client

    def synchronize_once(self, *, limit: int = 25) -> tuple[int, int]:
        from rolling_thunder.home_platform import HomePlatformError

        sent = failed = 0
        for qso_id, index, record in self._repository.pending(limit=limit):
            try:
                upload = self._client.upload_ft8_period
                upload(qso_id, index, record)
                self._repository.acknowledge(qso_id, index)
                sent += 1
            except (HomePlatformError, OSError, sqlite3.Error):
                failed += 1
                # Fail closed: next scheduled cycle retries with identical identity.
        return sent, failed
