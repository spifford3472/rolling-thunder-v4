"""SQLite storage initialization and schema migration for Rolling Thunder."""

import sqlite3
from pathlib import Path
from typing import Final

CURRENT_SCHEMA_VERSION: Final = 14

_MIGRATIONS: Final[dict[int, tuple[str, ...]]] = {
    1: (
        """
        CREATE TABLE schema_metadata (
            singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
            schema_version INTEGER NOT NULL CHECK (schema_version >= 0),
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        INSERT INTO schema_metadata (
            singleton_id,
            schema_version
        )
        VALUES (1, 0)
        """,
    ),
    2: (
        """
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
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE INDEX contacts_started_at_index
        ON contacts (started_at DESC)
        """,
        """
        CREATE INDEX contacts_synchronization_state_index
        ON contacts (synchronization_state, started_at)
        """,
        """
        CREATE INDEX contacts_callsign_index
        ON contacts (callsign, started_at DESC)
        """,
    ),
    3: (
        """
        CREATE TABLE contact_sync_retries (
            contact_id TEXT PRIMARY KEY,
            attempt_count INTEGER NOT NULL CHECK (attempt_count >= 1),
            next_attempt_at TEXT NOT NULL,
            last_error TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (contact_id)
                REFERENCES contacts (contact_id)
                ON DELETE CASCADE
        )
        """,
        """
        CREATE INDEX contact_sync_retries_due_index
        ON contact_sync_retries (next_attempt_at, contact_id)
        """,
    ),
    4: (
        """
        CREATE TABLE pota_spot_cache_metadata (
            singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
            last_success_at TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE pota_spot_cache (
            position INTEGER PRIMARY KEY CHECK (position >= 0),
            activator TEXT NOT NULL,
            park_reference TEXT NOT NULL,
            park_name TEXT,
            frequency_hz INTEGER NOT NULL
                CHECK (frequency_hz > 0 AND frequency_hz <= 300000000000),
            mode TEXT NOT NULL
                CHECK (mode IN ('AM', 'CW', 'DATA', 'FM', 'LSB', 'USB')),
            spotted_at TEXT NOT NULL,
            comments TEXT CHECK (
                comments IS NULL OR length(comments) <= 500
            )
        )
        """,
    ),
    5: (
        "ALTER TABLE pota_spot_cache ADD COLUMN spot_mode TEXT",
        "ALTER TABLE pota_spot_cache ADD COLUMN location_code TEXT",
        "ALTER TABLE pota_spot_cache ADD COLUMN latitude REAL",
        "ALTER TABLE pota_spot_cache ADD COLUMN longitude REAL",
    ),
    6: (
        "ALTER TABLE contacts ADD COLUMN my_grid TEXT",
        "ALTER TABLE contacts ADD COLUMN pota_reference TEXT",
        """
        ALTER TABLE contacts
        ADD COLUMN grid_source TEXT
        CHECK (
            grid_source IS NULL
            OR grid_source IN ('pota_park', 'qrz')
        )
        """,
        """
        ALTER TABLE contacts
        ADD COLUMN enrichment_state TEXT NOT NULL DEFAULT 'ready'
        CHECK (enrichment_state IN ('ready', 'pending_qrz'))
        """,
        """
        CREATE INDEX contacts_sync_enrichment_index
        ON contacts (
            synchronization_state,
            enrichment_state,
            started_at
        )
        """,
    ),
    7: (
        """
        CREATE TABLE forge_spot_cache_metadata (
            singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
            snapshot_revision INTEGER NOT NULL CHECK (snapshot_revision >= 0),
            generated_at TEXT NOT NULL,
            received_at TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE forge_spot_cache (
            position INTEGER PRIMARY KEY CHECK (position >= 0),
            provider TEXT NOT NULL CHECK (provider IN ('pota', 'dx')),
            stable_key TEXT NOT NULL UNIQUE,
            callsign TEXT NOT NULL,
            operator_name TEXT CHECK (
                operator_name IS NULL OR length(operator_name) <= 200
            ),
            grid TEXT,
            frequency_hz INTEGER NOT NULL
                CHECK (frequency_hz > 0 AND frequency_hz <= 300000000000),
            mode TEXT NOT NULL
                CHECK (mode IN ('AM', 'CW', 'DATA', 'FM', 'LSB', 'USB')),
            display_mode TEXT NOT NULL CHECK (
                length(display_mode) >= 1 AND length(display_mode) <= 40
            ),
            spotted_at TEXT NOT NULL,
            pota_park_reference TEXT,
            pota_park_name TEXT CHECK (
                pota_park_name IS NULL OR length(pota_park_name) <= 200
            ),
            pota_location_code TEXT CHECK (
                pota_location_code IS NULL OR length(pota_location_code) <= 100
            ),
            pota_latitude REAL CHECK (
                pota_latitude IS NULL OR (pota_latitude >= -90 AND pota_latitude <= 90)
            ),
            pota_longitude REAL CHECK (
                pota_longitude IS NULL OR (pota_longitude >= -180 AND pota_longitude <= 180)
            ),
            CHECK (
                (provider = 'pota' AND pota_park_reference IS NOT NULL)
                OR
                (provider = 'dx' AND pota_park_reference IS NULL)
            ),
            CHECK (
                (pota_latitude IS NULL AND pota_longitude IS NULL)
                OR
                (pota_latitude IS NOT NULL AND pota_longitude IS NOT NULL)
            )
        )
        """,
        """
        CREATE TABLE forge_spot_cache_source_metadata (
            spot_position INTEGER NOT NULL,
            metadata_position INTEGER NOT NULL CHECK (metadata_position >= 0),
            metadata_key TEXT NOT NULL CHECK (
                length(metadata_key) >= 1 AND length(metadata_key) <= 100
            ),
            metadata_value TEXT NOT NULL CHECK (
                length(metadata_value) >= 1 AND length(metadata_value) <= 500
            ),
            PRIMARY KEY (spot_position, metadata_position),
            UNIQUE (spot_position, metadata_key),
            FOREIGN KEY (spot_position)
                REFERENCES forge_spot_cache (position)
                ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE forge_spot_cache_provider_health (
            provider TEXT PRIMARY KEY CHECK (provider IN ('pota', 'dx')),
            status TEXT NOT NULL CHECK (
                status IN ('starting', 'healthy', 'degraded', 'unavailable')
            ),
            active_spot_count INTEGER NOT NULL CHECK (active_spot_count >= 0),
            last_attempt_at TEXT,
            last_success_at TEXT,
            last_error TEXT CHECK (
                last_error IS NULL OR length(last_error) <= 500
            )
        )
        """,
    ),
    8: (
        """
        CREATE TABLE operator_preferences (
            preference_key TEXT PRIMARY KEY CHECK (
                length(preference_key) >= 1 AND length(preference_key) <= 100
            ),
            preference_value TEXT NOT NULL CHECK (
                length(preference_value) <= 500
            ),
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
    ),
    9: (
        """
        CREATE TABLE forge_weather_cache (
            singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
            revision INTEGER NOT NULL CHECK (revision > 0),
            source_at TEXT NOT NULL,
            received_at TEXT NOT NULL,
            payload_json TEXT NOT NULL CHECK (length(payload_json) >= 2),
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
    ),
    10: (
        """
        CREATE TABLE forge_weather_alert_cache (
            singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
            revision INTEGER NOT NULL CHECK (revision > 0),
            fetched_at TEXT NOT NULL,
            received_at TEXT NOT NULL,
            payload_json TEXT NOT NULL CHECK (length(payload_json) >= 2),
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE weather_alert_notification_ledger (
            alert_id TEXT PRIMARY KEY CHECK (
                length(alert_id) >= 1 AND length(alert_id) <= 512
            ),
            event TEXT NOT NULL CHECK (
                length(event) >= 1 AND length(event) <= 160
            ),
            claimed_at TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE INDEX weather_alert_notification_claimed_at_index
        ON weather_alert_notification_ledger (claimed_at)
        """,
    ),
    11: (
        """
        CREATE TABLE repeater_active_overrides (
            repeater_identity TEXT PRIMARY KEY CHECK (
                length(repeater_identity) >= 1
                AND length(repeater_identity) <= 500
            ),
            active INTEGER NOT NULL CHECK (active IN (0, 1)),
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
    ),
    12: (
        """
        CREATE TABLE contact_sync_retries_v12_backup AS
        SELECT
            contact_id,
            attempt_count,
            next_attempt_at,
            last_error,
            updated_at
        FROM contact_sync_retries
        """,
        "DROP TABLE contact_sync_retries",
        """
        CREATE TABLE contacts_v12 (
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
        )
        """,
        """
        INSERT INTO contacts_v12 (
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
        )
        SELECT
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
        FROM contacts
        """,
        "DROP TABLE contacts",
        "ALTER TABLE contacts_v12 RENAME TO contacts",
        """
        CREATE INDEX contacts_started_at_index
        ON contacts (started_at DESC)
        """,
        """
        CREATE INDEX contacts_synchronization_state_index
        ON contacts (synchronization_state, started_at)
        """,
        """
        CREATE INDEX contacts_callsign_index
        ON contacts (callsign, started_at DESC)
        """,
        """
        CREATE INDEX contacts_sync_enrichment_index
        ON contacts (
            synchronization_state,
            enrichment_state,
            started_at
        )
        """,
        """
        CREATE TABLE contact_sync_retries (
            contact_id TEXT PRIMARY KEY,
            attempt_count INTEGER NOT NULL CHECK (attempt_count >= 1),
            next_attempt_at TEXT NOT NULL,
            last_error TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (contact_id)
                REFERENCES contacts (contact_id)
                ON DELETE CASCADE
        )
        """,
        """
        INSERT INTO contact_sync_retries (
            contact_id,
            attempt_count,
            next_attempt_at,
            last_error,
            updated_at
        )
        SELECT
            contact_id,
            attempt_count,
            next_attempt_at,
            last_error,
            updated_at
        FROM contact_sync_retries_v12_backup
        """,
        "DROP TABLE contact_sync_retries_v12_backup",
        """
        CREATE INDEX contact_sync_retries_due_index
        ON contact_sync_retries (next_attempt_at, contact_id)
        """,
    ),
    13: (
        """
        CREATE TABLE pota_worked_markers (
            utc_date TEXT NOT NULL CHECK (length(utc_date) = 10),
            callsign TEXT NOT NULL CHECK (
                length(callsign) >= 3 AND length(callsign) <= 32
            ),
            band TEXT NOT NULL CHECK (
                band IN (
                    '160m', '80m', '60m', '40m', '30m', '20m',
                    '17m', '15m', '12m', '10m', '6m'
                )
            ),
            display_mode TEXT NOT NULL CHECK (
                length(display_mode) >= 1 AND length(display_mode) <= 20
            ),
            worked_at TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (utc_date, callsign, band, display_mode)
        )
        """,
        """
        CREATE INDEX pota_worked_markers_day_index
        ON pota_worked_markers (utc_date, worked_at)
        """,
    ),
    14: (
        """
        CREATE TABLE contact_sync_retries_v14_backup AS
        SELECT
            contact_id,
            attempt_count,
            next_attempt_at,
            last_error,
            updated_at
        FROM contact_sync_retries
        """,
        "DROP TABLE contact_sync_retries",
        """
        CREATE TABLE contacts_v14 (
            contact_id TEXT PRIMARY KEY,
            callsign TEXT NOT NULL,
            frequency_hz INTEGER NOT NULL
                CHECK (frequency_hz > 0 AND frequency_hz <= 300000000000),
            mode TEXT NOT NULL
                CHECK (mode IN ('AM', 'CW', 'DATA', 'DMR', 'FT8', 'FM', 'LSB', 'USB')),
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
        )
        """,
        """
        INSERT INTO contacts_v14 (
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
        )
        SELECT
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
        FROM contacts
        """,
        "DROP TABLE contacts",
        "ALTER TABLE contacts_v14 RENAME TO contacts",
        """
        CREATE INDEX contacts_started_at_index
        ON contacts (started_at DESC)
        """,
        """
        CREATE INDEX contacts_synchronization_state_index
        ON contacts (synchronization_state, started_at)
        """,
        """
        CREATE INDEX contacts_callsign_index
        ON contacts (callsign, started_at DESC)
        """,
        """
        CREATE INDEX contacts_sync_enrichment_index
        ON contacts (
            synchronization_state,
            enrichment_state,
            started_at
        )
        """,
        """
        CREATE TABLE contact_sync_retries (
            contact_id TEXT PRIMARY KEY,
            attempt_count INTEGER NOT NULL CHECK (attempt_count >= 1),
            next_attempt_at TEXT NOT NULL,
            last_error TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (contact_id)
                REFERENCES contacts (contact_id)
                ON DELETE CASCADE
        )
        """,
        """
        INSERT INTO contact_sync_retries (
            contact_id,
            attempt_count,
            next_attempt_at,
            last_error,
            updated_at
        )
        SELECT
            contact_id,
            attempt_count,
            next_attempt_at,
            last_error,
            updated_at
        FROM contact_sync_retries_v14_backup
        """,
        "DROP TABLE contact_sync_retries_v14_backup",
        """
        CREATE INDEX contact_sync_retries_due_index
        ON contact_sync_retries (next_attempt_at, contact_id)
        """,
    )
}


class StorageError(Exception):
    """Raised when local application storage cannot be initialized."""


def _schema_metadata_exists(connection: sqlite3.Connection) -> bool:
    """Return whether the schema metadata table exists."""
    result = connection.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table'
          AND name = 'schema_metadata'
        """
    ).fetchone()

    return result is not None


def _read_schema_version(connection: sqlite3.Connection) -> int:
    """Read the database schema version, treating a new database as version zero."""
    if not _schema_metadata_exists(connection):
        return 0

    result = connection.execute(
        """
        SELECT schema_version
        FROM schema_metadata
        WHERE singleton_id = 1
        """
    ).fetchone()

    if result is None:
        raise StorageError("Database schema metadata is missing its required version record.")

    version = result[0]

    if not isinstance(version, int) or version < 0:
        raise StorageError("Database schema metadata contains an invalid version.")

    return version


def _apply_migrations(
    connection: sqlite3.Connection,
    current_version: int,
) -> int:
    """Apply pending database migrations transactionally."""
    if current_version > CURRENT_SCHEMA_VERSION:
        raise StorageError(
            "Database schema version "
            f"{current_version} is newer than supported version "
            f"{CURRENT_SCHEMA_VERSION}."
        )

    for target_version in range(current_version + 1, CURRENT_SCHEMA_VERSION + 1):
        migration = _MIGRATIONS.get(target_version)

        if migration is None:
            raise StorageError(f"Database migration {target_version} is not available.")

        try:
            connection.execute("BEGIN")

            for statement in migration:
                connection.execute(statement)

            connection.execute(
                """
                UPDATE schema_metadata
                SET schema_version = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE singleton_id = 1
                """,
                (target_version,),
            )

            connection.commit()
        except sqlite3.Error:
            connection.rollback()
            raise

    return CURRENT_SCHEMA_VERSION


def initialize_database(database_path: Path) -> int:
    """Create, migrate, and validate the configured SQLite database."""
    try:
        database_path.parent.mkdir(parents=True, exist_ok=True)

        with sqlite3.connect(database_path) as connection:
            connection.execute("PRAGMA foreign_keys = ON")

            foreign_keys_enabled = connection.execute("PRAGMA foreign_keys").fetchone()

            if foreign_keys_enabled != (1,):
                raise StorageError(
                    f"SQLite foreign-key enforcement could not be enabled: {database_path}"
                )

            current_version = _read_schema_version(connection)
            return _apply_migrations(connection, current_version)
    except StorageError:
        raise
    except (OSError, sqlite3.Error) as error:
        raise StorageError(
            f"Database could not be initialized: {database_path}: {error}"
        ) from error
