"""Tests for DMR contact-mode persistence and the version-12 schema migration."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from rolling_thunder.domain import Contact, RadioMode
from rolling_thunder.storage import CURRENT_SCHEMA_VERSION, initialize_database

_EXISTING_CONTACT_ID = "00000000-0000-0000-0000-000000000192"


def _create_version_11_database(database_path: Path) -> None:
    """Create the contact/retry portion of the production version-11 schema."""
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            PRAGMA foreign_keys = ON;

            CREATE TABLE schema_metadata (
                singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                schema_version INTEGER NOT NULL CHECK (schema_version >= 0),
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            INSERT INTO schema_metadata (singleton_id, schema_version)
            VALUES (1, 11);

            CREATE TABLE contacts (
                contact_id TEXT PRIMARY KEY,
                callsign TEXT NOT NULL,
                frequency_hz INTEGER NOT NULL
                    CHECK (frequency_hz > 0 AND frequency_hz <= 300000000000),
                mode TEXT NOT NULL
                    CHECK (mode IN ('AM', 'CW', 'DATA', 'FM', 'LSB', 'USB')),
                started_at TEXT NOT NULL,
                rst_sent TEXT NOT NULL,
                rst_received TEXT NOT NULL,
                grid TEXT,
                notes TEXT CHECK (notes IS NULL OR length(notes) <= 2000),
                synchronization_state TEXT NOT NULL DEFAULT 'pending'
                    CHECK (
                        synchronization_state IN (
                            'pending',
                            'synchronized',
                            'failed'
                        )
                    ),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                my_grid TEXT,
                pota_reference TEXT,
                grid_source TEXT
                    CHECK (
                        grid_source IS NULL
                        OR grid_source IN ('pota_park', 'qrz')
                    ),
                enrichment_state TEXT NOT NULL DEFAULT 'ready'
                    CHECK (enrichment_state IN ('ready', 'pending_qrz'))
            );

            CREATE INDEX contacts_started_at_index
            ON contacts (started_at DESC);

            CREATE INDEX contacts_synchronization_state_index
            ON contacts (synchronization_state, started_at);

            CREATE INDEX contacts_callsign_index
            ON contacts (callsign, started_at DESC);

            CREATE INDEX contacts_sync_enrichment_index
            ON contacts (
                synchronization_state,
                enrichment_state,
                started_at
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

            CREATE INDEX contact_sync_retries_due_index
            ON contact_sync_retries (next_attempt_at, contact_id);
            """
        )
        connection.execute(
            """
            INSERT INTO contacts (
                contact_id,
                callsign,
                frequency_hz,
                mode,
                started_at,
                rst_sent,
                rst_received,
                grid,
                notes,
                synchronization_state,
                created_at,
                updated_at,
                my_grid,
                pota_reference,
                grid_source,
                enrichment_state
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _EXISTING_CONTACT_ID,
                "W8O",
                14_250_000,
                "USB",
                "2026-08-15T20:00:00Z",
                "59",
                "59",
                "EN80aa",
                "pre-DMR contact",
                "failed",
                "2026-08-15 20:00:01",
                "2026-08-15 20:00:02",
                "EM79xm",
                "US-0732",
                "pota_park",
                "ready",
            ),
        )
        connection.execute(
            """
            INSERT INTO contact_sync_retries (
                contact_id,
                attempt_count,
                next_attempt_at,
                last_error,
                updated_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                _EXISTING_CONTACT_ID,
                3,
                "2026-08-16T00:30:00Z",
                "Forge unavailable",
                "2026-08-16 00:20:00",
            ),
        )
        connection.commit()


def _read_index_names(connection: sqlite3.Connection, table_name: str) -> set[str]:
    rows = connection.execute(f"PRAGMA index_list({table_name})").fetchall()
    return {str(row[1]) for row in rows}


def test_contact_domain_accepts_dmr_mode() -> None:
    contact = Contact(
        callsign="KC9KPJ",
        frequency_hz=434_537_500,
        mode="dmr",
        started_at=datetime(2026, 8, 16, 0, 7, 8, tzinfo=UTC),
        rst_sent="59",
        rst_received="59",
        my_grid="EM79xm",
    )

    assert contact.mode is RadioMode.DMR
    assert contact.model_dump(mode="json")["mode"] == "DMR"


def test_version_12_migration_preserves_contact_retry_and_constraints(tmp_path: Path) -> None:
    database_path = tmp_path / "rolling-thunder-v11.db"
    _create_version_11_database(database_path)

    assert initialize_database(database_path) == CURRENT_SCHEMA_VERSION == 18

    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")

        contact = connection.execute(
            """
            SELECT
                callsign,
                frequency_hz,
                mode,
                started_at,
                rst_sent,
                rst_received,
                grid,
                notes,
                synchronization_state,
                created_at,
                updated_at,
                my_grid,
                pota_reference,
                grid_source,
                enrichment_state
            FROM contacts
            WHERE contact_id = ?
            """,
            (_EXISTING_CONTACT_ID,),
        ).fetchone()
        assert contact == (
            "W8O",
            14_250_000,
            "USB",
            "2026-08-15T20:00:00Z",
            "59",
            "59",
            "EN80aa",
            "pre-DMR contact",
            "failed",
            "2026-08-15 20:00:01",
            "2026-08-15 20:00:02",
            "EM79xm",
            "US-0732",
            "pota_park",
            "ready",
        )

        retry = connection.execute(
            """
            SELECT attempt_count, next_attempt_at, last_error, updated_at
            FROM contact_sync_retries
            WHERE contact_id = ?
            """,
            (_EXISTING_CONTACT_ID,),
        ).fetchone()
        assert retry == (
            3,
            "2026-08-16T00:30:00Z",
            "Forge unavailable",
            "2026-08-16 00:20:00",
        )

        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert {
            "contacts_started_at_index",
            "contacts_synchronization_state_index",
            "contacts_callsign_index",
            "contacts_sync_enrichment_index",
        }.issubset(_read_index_names(connection, "contacts"))
        assert "contact_sync_retries_due_index" in _read_index_names(
            connection,
            "contact_sync_retries",
        )

        connection.execute(
            """
            INSERT INTO contacts (
                contact_id,
                callsign,
                frequency_hz,
                mode,
                started_at,
                rst_sent,
                rst_received,
                my_grid,
                synchronization_state
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "00000000-0000-0000-0000-000000000193",
                "KC9KPJ",
                434_537_500,
                "DMR",
                "2026-08-16T00:07:08Z",
                "59",
                "59",
                "EM79xm",
                "pending",
            ),
        )
        connection.commit()

        stored_mode = connection.execute(
            "SELECT mode FROM contacts WHERE callsign = 'KC9KPJ'"
        ).fetchone()
        assert stored_mode == ("DMR",)
