"""Isolated Forge archive for individual FT8 transmissions, safe under retries."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from uuid import UUID

from rolling_thunder.ft8.hardware_transmit import FT8TransmitPeriodTelemetry


class ForgeFT8PeriodConflict(RuntimeError):
    """One emission identity was reused with changed source telemetry."""


class ForgeFT8PeriodRepository:
    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS forge_ft8_transmit_period (
                qso_id TEXT NOT NULL,
                emission_index INTEGER NOT NULL CHECK(emission_index >= 1),
                payload_sha256 TEXT NOT NULL,
                started_at_utc TEXT NOT NULL,
                ended_at_utc TEXT NOT NULL,
                frequency_hz INTEGER NOT NULL,
                configured_power_watts INTEGER,
                power_readback_verified INTEGER NOT NULL,
                transmitted INTEGER NOT NULL,
                PRIMARY KEY(qso_id, emission_index)
            )""")
            if not any(row[1] == "transmit_audio_offset_hz" for row in db.execute("PRAGMA table_info(forge_ft8_transmit_period)")):
                db.execute("ALTER TABLE forge_ft8_transmit_period ADD COLUMN transmit_audio_offset_hz INTEGER")
            db.execute(
                "CREATE INDEX IF NOT EXISTS forge_ft8_transmit_period_time "
                "ON forge_ft8_transmit_period(started_at_utc, frequency_hz)"
            )

    def persist(
        self,
        qso_id: UUID,
        emission_index: int,
        record: FT8TransmitPeriodTelemetry,
    ) -> bool:
        """True for a new row, False for an identical replay."""
        if qso_id != record.qso_id or emission_index < 1:
            raise ValueError("invalid emission identity")
        if record.started_at_utc.tzinfo is None or record.ended_at_utc.tzinfo is None:
            raise ValueError("transmission timestamps require timezone")
        if record.ended_at_utc < record.started_at_utc:
            raise ValueError("end timestamp precedes start")
        if record.power_readback_verified != (record.configured_power_watts is not None):
            raise ValueError("configured power provenance conflict")
        if record.transmit_audio_offset_hz is not None and not 200 <= record.transmit_audio_offset_hz <= 3500:
            raise ValueError("invalid transmit audio offset")
        payload = {
            **asdict(record),
            "qso_id": str(record.qso_id),
            "started_at_utc": record.started_at_utc.isoformat(),
            "ended_at_utc": record.ended_at_utc.isoformat(),
        }
        if record.transmit_audio_offset_hz is None:
            payload.pop("transmit_audio_offset_hz")  # preserve legacy replay digests
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        with sqlite3.connect(self._path) as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT payload_sha256 FROM forge_ft8_transmit_period "
                "WHERE qso_id=? AND emission_index=?",
                (str(qso_id), emission_index),
            ).fetchone()
            if existing is not None:
                if existing[0] != digest:
                    raise ForgeFT8PeriodConflict("emission replay changed immutable telemetry")
                return False
            db.execute(
                "INSERT INTO forge_ft8_transmit_period (qso_id,emission_index,payload_sha256,started_at_utc,ended_at_utc,frequency_hz,configured_power_watts,power_readback_verified,transmitted,transmit_audio_offset_hz) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    str(qso_id), emission_index, digest,
                    record.started_at_utc.isoformat(),
                    record.ended_at_utc.isoformat(),
                    record.frequency_hz,
                    record.configured_power_watts,
                    int(record.power_readback_verified),
                    int(record.transmitted), record.transmit_audio_offset_hz,
                ),
            )
            return True
