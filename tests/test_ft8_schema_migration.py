"""FT8 contact and telemetry schema migration preservation tests."""

import sqlite3
from pathlib import Path
from uuid import UUID

from rolling_thunder.contact_repository import ContactRepository
from rolling_thunder.domain import Contact, RadioMode
from rolling_thunder.storage import CURRENT_SCHEMA_VERSION, initialize_database


def _create_v13_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE schema_metadata (
                singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                schema_version INTEGER NOT NULL CHECK (schema_version >= 0),
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO schema_metadata (singleton_id, schema_version)
            VALUES (1, 13);

            CREATE TABLE contacts (
                contact_id TEXT PRIMARY KEY,
                callsign TEXT NOT NULL,
                frequency_hz INTEGER NOT NULL
                    CHECK (frequency_hz > 0 AND frequency_hz <= 300000000000),
                mode TEXT NOT NULL
                    CHECK (mode IN ('AM', 'CW', 'DATA', 'DMR', 'FM', 'LSB', 'USB')),
                started_at TEXT NOT NULL,
                rst_sent TEXT NOT NULL,
                rst_received TEXT NOT NULL,
                grid TEXT,
                notes TEXT CHECK (notes IS NULL OR length(notes) <= 2000),
                synchronization_state TEXT NOT NULL DEFAULT 'pending'
                    CHECK (synchronization_state IN ('pending', 'synchronized', 'failed')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                my_grid TEXT,
                pota_reference TEXT,
                grid_source TEXT
                    CHECK (grid_source IS NULL OR grid_source IN ('pota_park', 'qrz')),
                enrichment_state TEXT NOT NULL DEFAULT 'ready'
                    CHECK (enrichment_state IN ('ready', 'pending_qrz'))
            );

            CREATE TABLE contact_sync_retries (
                contact_id TEXT PRIMARY KEY,
                attempt_count INTEGER NOT NULL CHECK (attempt_count >= 1),
                next_attempt_at TEXT NOT NULL,
                last_error TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (contact_id)
                    REFERENCES contacts (contact_id)
                    ON DELETE CASCADE
            );
            """
        )
        connection.execute(
            """
            INSERT INTO contacts (
                contact_id, callsign, frequency_hz, mode, started_at,
                rst_sent, rst_received, grid, notes, synchronization_state,
                my_grid, pota_reference, grid_source, enrichment_state
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "00000000-0000-0000-0000-000000000831",
                "W1AW",
                14_250_000,
                "USB",
                "2026-09-30T20:00:00Z",
                "59",
                "57",
                "FN31pr",
                "legacy row",
                "failed",
                "EM79xm",
                None,
                "qrz",
                "ready",
            ),
        )
        connection.execute(
            """
            INSERT INTO contact_sync_retries (
                contact_id, attempt_count, next_attempt_at, last_error
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                "00000000-0000-0000-0000-000000000831",
                2,
                "2026-09-30T20:10:00Z",
                "temporary outage",
            ),
        )
        connection.commit()


def test_v14_migration_preserves_existing_contact_and_retry_and_allows_ft8(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "rolling-thunder.db"
    _create_v13_database(database_path)

    assert initialize_database(database_path) == CURRENT_SCHEMA_VERSION
    assert CURRENT_SCHEMA_VERSION == 18

    repository = ContactRepository(database_path)
    legacy = repository.get(UUID("00000000-0000-0000-0000-000000000831"))
    assert legacy is not None
    assert legacy.callsign == "W1AW"
    assert legacy.mode is RadioMode.USB
    assert legacy.notes == "legacy row"
    assert legacy.my_grid == "EM79xm"

    with sqlite3.connect(database_path) as connection:
        outbox_table = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = 'ft8_performance_outbox'
            """
        ).fetchone()
        assert outbox_table == ("ft8_performance_outbox",)

        retry = connection.execute(
            """
            SELECT attempt_count, next_attempt_at, last_error
            FROM contact_sync_retries
            WHERE contact_id = ?
            """,
            ("00000000-0000-0000-0000-000000000831",),
        ).fetchone()
    assert retry == (2, "2026-09-30T20:10:00Z", "temporary outage")

    repository.add(
        Contact(
            contact_id=UUID("00000000-0000-0000-0000-000000000832"),
            callsign="K1ABC",
            frequency_hz=14_074_000,
            mode=RadioMode.FT8,
            started_at="2026-09-30T20:15:01Z",
            rst_sent="+14",
            rst_received="-10",
            my_grid="EM79xm",
        )
    )
    ft8 = repository.get(UUID("00000000-0000-0000-0000-000000000832"))
    assert ft8 is not None
    assert ft8.mode is RadioMode.FT8
