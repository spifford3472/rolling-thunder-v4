"""Dedicated Forge persistence for FT8 machine-analysis attempts."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from json import dumps
from pathlib import Path

from rolling_thunder.ft8.performance import (
    FT8PerformanceAttempt,
    FT8PerformanceUploadDisposition,
    FT8PerformanceUploadResult,
)

Clock = Callable[[], datetime]
_FORGE_FT8_SCHEMA_VERSION = 1


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ForgeFT8PerformanceStorageError(RuntimeError):
    """Raised when the Forge performance database cannot operate safely."""


class ForgeFT8PerformanceConflictError(RuntimeError):
    """Raised when one attempt UUID is replayed with changed data."""


class ForgeFT8PerformanceRepository:
    """Versioned SQLite store for queryable FT8 performance telemetry."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        try:
            database_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(database_path) as connection:
                self._migrate(connection)
        except (OSError, sqlite3.Error) as error:
            raise ForgeFT8PerformanceStorageError(
                f"Forge FT8 performance storage could not be initialized: {database_path}"
            ) from error

    def persist(
        self,
        attempt: FT8PerformanceAttempt,
    ) -> FT8PerformanceUploadDisposition:
        """Insert exactly once or accept an identical replay."""
        payload_sha256 = _payload_sha256(attempt)
        try:
            with sqlite3.connect(self._database_path) as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    """
                    SELECT payload_sha256
                    FROM ft8_performance_attempts
                    WHERE attempt_id = ?
                    """,
                    (str(attempt.attempt_id),),
                ).fetchone()
                if row is not None:
                    if row[0] != payload_sha256:
                        connection.rollback()
                        raise ForgeFT8PerformanceConflictError(
                            "FT8 performance attempt UUID was replayed with different data: "
                            f"{attempt.attempt_id}"
                        )
                    connection.commit()
                    return FT8PerformanceUploadDisposition.ALREADY_EXISTS

                connection.execute(
                    """
                    INSERT INTO ft8_performance_attempts (
                        attempt_id,
                        payload_sha256,
                        callsign,
                        outcome,
                        success,
                        terminal_state,
                        terminal_reason,
                        started_at_utc,
                        ended_at_utc,
                        utc_date,
                        band,
                        dial_frequency_hz,
                        mode,
                        tx_power_target_watts,
                        power_meter_raw,
                        swr_meter_raw,
                        alc_meter_raw,
                        sent_report_db,
                        received_report_db,
                        local_grid,
                        remote_grid,
                        distance_km,
                        audio_frequency_hz,
                        pota_cq,
                        attempt_count,
                        last_qso_state,
                        voacap_probability,
                        voacap_predicted_snr_db,
                        voacap_path,
                        analysis_schema_version
                    )
                    VALUES (
                        :attempt_id,
                        :payload_sha256,
                        :callsign,
                        :outcome,
                        :success,
                        :terminal_state,
                        :terminal_reason,
                        :started_at_utc,
                        :ended_at_utc,
                        :utc_date,
                        :band,
                        :dial_frequency_hz,
                        :mode,
                        :tx_power_target_watts,
                        :power_meter_raw,
                        :swr_meter_raw,
                        :alc_meter_raw,
                        :sent_report_db,
                        :received_report_db,
                        :local_grid,
                        :remote_grid,
                        :distance_km,
                        :audio_frequency_hz,
                        :pota_cq,
                        :attempt_count,
                        :last_qso_state,
                        :voacap_probability,
                        :voacap_predicted_snr_db,
                        :voacap_path,
                        :analysis_schema_version
                    )
                    """,
                    {
                        "attempt_id": str(attempt.attempt_id),
                        "payload_sha256": payload_sha256,
                        "callsign": attempt.callsign,
                        "outcome": attempt.outcome.value,
                        "success": int(attempt.success),
                        "terminal_state": attempt.terminal_state,
                        "terminal_reason": attempt.terminal_reason,
                        "started_at_utc": attempt.started_at_utc.isoformat().replace(
                            "+00:00", "Z"
                        ),
                        "ended_at_utc": attempt.ended_at_utc.isoformat().replace(
                            "+00:00", "Z"
                        ),
                        "utc_date": attempt.utc_date.isoformat(),
                        "band": attempt.band,
                        "dial_frequency_hz": attempt.dial_frequency_hz,
                        "mode": attempt.mode,
                        "tx_power_target_watts": attempt.tx_power_target_watts,
                        "power_meter_raw": attempt.power_meter_raw,
                        "swr_meter_raw": attempt.swr_meter_raw,
                        "alc_meter_raw": attempt.alc_meter_raw,
                        "sent_report_db": attempt.sent_report_db,
                        "received_report_db": attempt.received_report_db,
                        "local_grid": attempt.local_grid,
                        "remote_grid": attempt.remote_grid,
                        "distance_km": attempt.distance_km,
                        "audio_frequency_hz": attempt.audio_frequency_hz,
                        "pota_cq": int(attempt.pota_cq),
                        "attempt_count": attempt.attempt_count,
                        "last_qso_state": attempt.last_qso_state,
                        "voacap_probability": attempt.voacap_probability,
                        "voacap_predicted_snr_db": attempt.voacap_predicted_snr_db,
                        "voacap_path": attempt.voacap_path,
                        "analysis_schema_version": attempt.analysis_schema_version,
                    },
                )
                connection.commit()
        except ForgeFT8PerformanceConflictError:
            raise
        except sqlite3.Error as error:
            raise ForgeFT8PerformanceStorageError(
                f"Forge FT8 performance persistence failed: {attempt.attempt_id}"
            ) from error
        return FT8PerformanceUploadDisposition.ACCEPTED

    def get_row(self, attempt_id: str) -> sqlite3.Row | None:
        """Read one structured row for diagnostics/tests."""
        try:
            with sqlite3.connect(self._database_path) as connection:
                connection.row_factory = sqlite3.Row
                return connection.execute(
                    """
                    SELECT *
                    FROM ft8_performance_attempts
                    WHERE attempt_id = ?
                    """,
                    (attempt_id,),
                ).fetchone()
        except sqlite3.Error as error:
            raise ForgeFT8PerformanceStorageError(
                f"Forge FT8 performance row could not be read: {attempt_id}"
            ) from error

    @staticmethod
    def _migrate(connection: sqlite3.Connection) -> None:
        """Create/upgrade the dedicated telemetry schema transactionally."""
        connection.execute("BEGIN")
        try:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS forge_ft8_performance_schema (
                    singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
                    schema_version INTEGER NOT NULL CHECK(schema_version >= 0),
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            row = connection.execute(
                """
                SELECT schema_version
                FROM forge_ft8_performance_schema
                WHERE singleton_id = 1
                """
            ).fetchone()
            if row is None:
                connection.execute(
                    """
                    INSERT INTO forge_ft8_performance_schema (
                        singleton_id,
                        schema_version
                    )
                    VALUES (1, 0)
                    """
                )
                current_version = 0
            else:
                current_version = int(row[0])

            if current_version > _FORGE_FT8_SCHEMA_VERSION:
                raise sqlite3.DatabaseError(
                    "Forge FT8 performance schema is newer than this application"
                )

            if current_version < 1:
                connection.execute(
                    """
                    CREATE TABLE ft8_performance_attempts (
                        attempt_id TEXT PRIMARY KEY,
                        payload_sha256 TEXT NOT NULL
                            CHECK(length(payload_sha256) = 64),
                        callsign TEXT NOT NULL,
                        outcome TEXT NOT NULL
                            CHECK(outcome IN (
                                'completed',
                                'aborted',
                                'retry_exhausted',
                                'error',
                                'preparation_failed'
                            )),
                        success INTEGER NOT NULL CHECK(success IN (0, 1)),
                        terminal_state TEXT NOT NULL,
                        terminal_reason TEXT,
                        started_at_utc TEXT NOT NULL,
                        ended_at_utc TEXT NOT NULL,
                        utc_date TEXT NOT NULL CHECK(length(utc_date) = 10),
                        band TEXT NOT NULL,
                        dial_frequency_hz INTEGER NOT NULL CHECK(dial_frequency_hz > 0),
                        mode TEXT NOT NULL CHECK(mode = 'FT8'),
                        tx_power_target_watts INTEGER NOT NULL CHECK(tx_power_target_watts > 0),
                        power_meter_raw INTEGER CHECK(
                            power_meter_raw IS NULL
                            OR power_meter_raw BETWEEN 0 AND 255
                        ),
                        swr_meter_raw INTEGER CHECK(
                            swr_meter_raw IS NULL
                            OR swr_meter_raw BETWEEN 0 AND 255
                        ),
                        alc_meter_raw INTEGER CHECK(
                            alc_meter_raw IS NULL
                            OR alc_meter_raw BETWEEN 0 AND 255
                        ),
                        sent_report_db INTEGER,
                        received_report_db INTEGER,
                        local_grid TEXT,
                        remote_grid TEXT,
                        distance_km REAL CHECK(distance_km IS NULL OR distance_km >= 0),
                        audio_frequency_hz INTEGER,
                        pota_cq INTEGER NOT NULL CHECK(pota_cq IN (0, 1)),
                        attempt_count INTEGER NOT NULL CHECK(attempt_count >= 0),
                        last_qso_state TEXT,
                        voacap_probability REAL,
                        voacap_predicted_snr_db REAL,
                        voacap_path TEXT,
                        analysis_schema_version INTEGER NOT NULL CHECK(
                            analysis_schema_version >= 1
                        ),
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX ft8_performance_attempts_date_band_index
                    ON ft8_performance_attempts (utc_date, band, started_at_utc)
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX ft8_performance_attempts_outcome_index
                    ON ft8_performance_attempts (outcome, started_at_utc)
                    """
                )
                connection.execute(
                    """
                    UPDATE forge_ft8_performance_schema
                    SET schema_version = 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE singleton_id = 1
                    """
                )

            connection.commit()
        except sqlite3.Error:
            connection.rollback()
            raise


class ForgeFT8PerformanceService:
    """Persist telemetry without invoking Wavelog or contact synchronization."""

    def __init__(
        self,
        repository: ForgeFT8PerformanceRepository,
        *,
        clock: Clock = _utc_now,
    ) -> None:
        self._repository = repository
        self._clock = clock

    def persist(self, attempt: FT8PerformanceAttempt) -> FT8PerformanceUploadResult:
        received_at = self._clock()
        if received_at.tzinfo is None or received_at.utcoffset() is None:
            raise ValueError("Forge FT8 performance clock must be timezone-aware")
        disposition = self._repository.persist(attempt)
        return FT8PerformanceUploadResult(
            attempt_id=attempt.attempt_id,
            disposition=disposition,
            received_at_utc=received_at,
        )


def _payload_sha256(attempt: FT8PerformanceAttempt) -> str:
    payload = dumps(
        attempt.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
