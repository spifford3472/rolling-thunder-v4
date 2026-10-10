"""Append-only local archive of individually keyed FT8 periods.

This store is independent of the terminal-attempt upload and makes no claim
that a configured CAT power is measured RF output power.
"""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
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
            db.execute("CREATE INDEX IF NOT EXISTS idx_ft8_transmit_period_time ON ft8_transmit_period(started_at_utc, frequency_hz)")

    def append(self, record: FT8TransmitPeriodTelemetry) -> None:
        if record.started_at_utc.tzinfo is None or record.ended_at_utc.tzinfo is None:
            raise ValueError("transmission timestamps require timezones")
        if record.ended_at_utc < record.started_at_utc:
            raise ValueError("transmission end precedes start")
        if record.power_readback_verified != (record.configured_power_watts is not None):
            raise ValueError("CAT power provenance must match recorded setting")
        with sqlite3.connect(self._path) as db:
            db.execute("BEGIN IMMEDIATE")
            index = db.execute(
                "SELECT COALESCE(MAX(emission_index),0)+1 FROM ft8_transmit_period WHERE qso_id=?",
                (str(record.qso_id),),
            ).fetchone()[0]
            db.execute("""INSERT INTO ft8_transmit_period VALUES (?,?,?,?,?,?,?,?)""", (
                str(record.qso_id), index,
                record.started_at_utc.astimezone(UTC).isoformat(),
                record.ended_at_utc.astimezone(UTC).isoformat(),
                record.configured_power_watts, int(record.power_readback_verified),
                record.frequency_hz, int(record.transmitted),
            ))

    def for_qso(self, qso_id: UUID) -> tuple[FT8TransmitPeriodTelemetry, ...]:
        with sqlite3.connect(self._path) as db:
            rows=db.execute("""SELECT started_at_utc,ended_at_utc,configured_power_watts,
                     power_readback_verified,frequency_hz,transmitted
                     FROM ft8_transmit_period WHERE qso_id=? ORDER BY emission_index""",
                     (str(qso_id),)).fetchall()
        return tuple(FT8TransmitPeriodTelemetry(
            qso_id, datetime.fromisoformat(start),datetime.fromisoformat(end),
            power,bool(verified),freq,bool(transmitted)
        ) for start,end,power,verified,freq,transmitted in rows)
