"""SQLite storage initialization and schema migration for Rolling Thunder."""

import sqlite3
from pathlib import Path
from typing import Final

CURRENT_SCHEMA_VERSION: Final = 23

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
    ),
    15: (
        """
        CREATE TABLE ft8_performance_outbox (
            attempt_id TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL CHECK(length(payload_json) >= 2),
            synchronization_state TEXT NOT NULL DEFAULT 'pending'
                CHECK (
                    synchronization_state IN (
                        'pending',
                        'synchronized',
                        'failed'
                    )
                ),
            retry_count INTEGER NOT NULL DEFAULT 0 CHECK(retry_count >= 0),
            next_attempt_at TEXT,
            last_error TEXT CHECK(last_error IS NULL OR length(last_error) <= 1000),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE INDEX ft8_performance_outbox_sync_index
        ON ft8_performance_outbox (
            synchronization_state,
            next_attempt_at,
            created_at
        )
        """,
    ),
    16: (
        "ALTER TABLE contacts ADD COLUMN my_latitude REAL",
        "ALTER TABLE contacts ADD COLUMN my_longitude REAL",
    ),
    17: (
        "ALTER TABLE contacts ADD COLUMN my_state TEXT",
        "ALTER TABLE contacts ADD COLUMN my_cq_zone INTEGER",
        "ALTER TABLE contacts ADD COLUMN my_itu_zone INTEGER",
    ),
    18: (
        """
        CREATE TABLE dx_worked_markers (
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
            worked_at TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (utc_date, callsign, band)
        )
        """,
        """
        CREATE INDEX dx_worked_markers_day_index
        ON dx_worked_markers (utc_date, worked_at)
        """,
    ),
    19: (
        "ALTER TABLE contacts ADD COLUMN source TEXT NOT NULL DEFAULT 'unknown'",
        "ALTER TABLE contacts ADD COLUMN tx_power_watts INTEGER",
        "ALTER TABLE contacts ADD COLUMN contact_weather_json TEXT",
        "ALTER TABLE contacts ADD COLUMN local_weather_json TEXT",
        "ALTER TABLE contacts ADD COLUMN weather_notes_enabled INTEGER NOT NULL DEFAULT 0",
    ),
    20: (
        "ALTER TABLE contacts ADD COLUMN contact_latitude REAL",
        "ALTER TABLE contacts ADD COLUMN contact_longitude REAL",
    ),
    21: (
        """
        CREATE TABLE antenna_catalog (
            antenna_id TEXT PRIMARY KEY CHECK (length(antenna_id) = 36),
            name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
            manufacturer TEXT CHECK (manufacturer IS NULL OR length(manufacturer) <= 200),
            model TEXT CHECK (model IS NULL OR length(model) <= 200),
            source TEXT NOT NULL CHECK (length(source) BETWEEN 1 AND 500),
            provenance_notes TEXT CHECK (
                provenance_notes IS NULL OR length(provenance_notes) <= 2000
            ),
            notes TEXT CHECK (notes IS NULL OR length(notes) <= 2000),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE antenna_band_associations (
            association_id TEXT PRIMARY KEY CHECK (length(association_id) = 36),
            antenna_id TEXT NOT NULL,
            label TEXT NOT NULL CHECK (length(label) BETWEEN 1 AND 40),
            region TEXT NOT NULL CHECK (region IN ('HF', 'VHF', 'UHF', 'other')),
            lower_hz INTEGER NOT NULL CHECK (lower_hz > 0),
            upper_hz INTEGER NOT NULL CHECK (upper_hz >= lower_hz),
            source TEXT NOT NULL CHECK (length(source) BETWEEN 1 AND 500),
            provenance_notes TEXT CHECK (
                provenance_notes IS NULL OR length(provenance_notes) <= 2000
            ),
            FOREIGN KEY (antenna_id) REFERENCES antenna_catalog (antenna_id)
                ON DELETE CASCADE
        )
        """,
        """
        CREATE INDEX antenna_band_associations_antenna_index
        ON antenna_band_associations (antenna_id, lower_hz, upper_hz)
        """,
        """
        CREATE TABLE antenna_gain_segments (
            gain_id TEXT PRIMARY KEY CHECK (length(gain_id) = 36),
            antenna_id TEXT NOT NULL,
            lower_hz INTEGER NOT NULL CHECK (lower_hz > 0),
            upper_hz INTEGER NOT NULL CHECK (upper_hz >= lower_hz),
            gain_db REAL NOT NULL,
            gain_unit TEXT NOT NULL CHECK (gain_unit IN ('dBi', 'dBd')),
            source TEXT NOT NULL CHECK (length(source) BETWEEN 1 AND 500),
            provenance_notes TEXT CHECK (
                provenance_notes IS NULL OR length(provenance_notes) <= 2000
            ),
            FOREIGN KEY (antenna_id) REFERENCES antenna_catalog (antenna_id)
                ON DELETE CASCADE,
            CHECK (gain_db = gain_db AND abs(gain_db) < 1.0e308)
        )
        """,
        """
        CREATE INDEX antenna_gain_segments_antenna_index
        ON antenna_gain_segments (antenna_id, lower_hz, upper_hz)
        """,
        """
        CREATE TABLE antenna_installations (
            installation_id TEXT PRIMARY KEY CHECK (length(installation_id) = 36),
            antenna_id TEXT NOT NULL,
            name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
            location_description TEXT NOT NULL CHECK (
                length(location_description) BETWEEN 1 AND 500
            ),
            losses_complete INTEGER NOT NULL CHECK (losses_complete IN (0, 1)),
            source TEXT NOT NULL CHECK (length(source) BETWEEN 1 AND 500),
            provenance_notes TEXT CHECK (
                provenance_notes IS NULL OR length(provenance_notes) <= 2000
            ),
            notes TEXT CHECK (notes IS NULL OR length(notes) <= 2000),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (antenna_id) REFERENCES antenna_catalog (antenna_id)
                ON DELETE RESTRICT
        )
        """,
        """
        CREATE INDEX antenna_installations_antenna_index
        ON antenna_installations (antenna_id)
        """,
        """
        CREATE TABLE antenna_loss_segments (
            loss_id TEXT PRIMARY KEY CHECK (length(loss_id) = 36),
            installation_id TEXT NOT NULL,
            name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
            lower_hz INTEGER NOT NULL CHECK (lower_hz > 0),
            upper_hz INTEGER NOT NULL CHECK (upper_hz >= lower_hz),
            loss_db REAL CHECK (
                loss_db IS NULL
                OR (loss_db >= 0 AND loss_db = loss_db AND loss_db < 1.0e308)
            ),
            source TEXT NOT NULL CHECK (length(source) BETWEEN 1 AND 500),
            provenance_notes TEXT CHECK (
                provenance_notes IS NULL OR length(provenance_notes) <= 2000
            ),
            FOREIGN KEY (installation_id) REFERENCES antenna_installations (installation_id)
                ON DELETE CASCADE
        )
        """,
        """
        CREATE INDEX antenna_loss_segments_installation_index
        ON antenna_loss_segments (installation_id, lower_hz, upper_hz)
        """,
        """
        CREATE TABLE antenna_installation_band_assignments (
            assignment_id TEXT PRIMARY KEY CHECK (length(assignment_id) = 36),
            installation_id TEXT NOT NULL,
            association_id TEXT NOT NULL,
            active INTEGER NOT NULL CHECK (active IN (0, 1)),
            source TEXT NOT NULL CHECK (length(source) BETWEEN 1 AND 500),
            provenance_notes TEXT CHECK (
                provenance_notes IS NULL OR length(provenance_notes) <= 2000
            ),
            UNIQUE (installation_id, association_id),
            FOREIGN KEY (installation_id) REFERENCES antenna_installations (installation_id)
                ON DELETE CASCADE,
            FOREIGN KEY (association_id) REFERENCES antenna_band_associations (association_id)
                ON DELETE RESTRICT
        )
        """,
        """
        CREATE TABLE antenna_mode_profiles (
            mode_profile_id TEXT PRIMARY KEY CHECK (length(mode_profile_id) = 36),
            name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 100),
            rf_envelope_duty REAL NOT NULL CHECK (
                rf_envelope_duty > 0 AND rf_envelope_duty <= 1
                AND rf_envelope_duty = rf_envelope_duty
            ),
            source TEXT NOT NULL CHECK (length(source) BETWEEN 1 AND 500),
            provenance_notes TEXT CHECK (
                provenance_notes IS NULL OR length(provenance_notes) <= 2000
            ),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE rf_exposure_scenarios (
            scenario_id TEXT PRIMARY KEY CHECK (length(scenario_id) = 36),
            installation_id TEXT NOT NULL,
            mode_profile_id TEXT NOT NULL,
            name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
            frequency_hz INTEGER NOT NULL CHECK (
                frequency_hz >= 300000 AND frequency_hz <= 100000000000
            ),
            forward_tx_watts REAL NOT NULL CHECK (
                forward_tx_watts > 0 AND forward_tx_watts = forward_tx_watts
                AND forward_tx_watts < 1.0e308
            ),
            controlled_tx_fraction REAL NOT NULL CHECK (
                controlled_tx_fraction > 0 AND controlled_tx_fraction <= 1
                AND controlled_tx_fraction = controlled_tx_fraction
            ),
            uncontrolled_tx_fraction REAL NOT NULL CHECK (
                uncontrolled_tx_fraction > 0 AND uncontrolled_tx_fraction <= 1
                AND uncontrolled_tx_fraction = uncontrolled_tx_fraction
            ),
            occupant_distance_m REAL NOT NULL DEFAULT 1.8288 CHECK (
                occupant_distance_m > 0 AND occupant_distance_m = occupant_distance_m
                AND occupant_distance_m < 1.0e308
            ),
            occupant_distance_verified INTEGER NOT NULL DEFAULT 0 CHECK (
                occupant_distance_verified IN (0, 1)
            ),
            ground_reflection_model TEXT NOT NULL CHECK (
                ground_reflection_model IN ('free_space', 'arrl_typical_ground')
            ),
            source TEXT NOT NULL CHECK (length(source) BETWEEN 1 AND 500),
            provenance_notes TEXT CHECK (
                provenance_notes IS NULL OR length(provenance_notes) <= 2000
            ),
            notes TEXT CHECK (notes IS NULL OR length(notes) <= 2000),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (installation_id) REFERENCES antenna_installations (installation_id)
                ON DELETE CASCADE,
            FOREIGN KEY (mode_profile_id) REFERENCES antenna_mode_profiles (mode_profile_id)
                ON DELETE RESTRICT
        )
        """,
        """
        CREATE INDEX rf_exposure_scenarios_installation_index
        ON rf_exposure_scenarios (installation_id, frequency_hz)
        """,
    ),
    22: (
        "ALTER TABLE contacts ADD COLUMN my_county TEXT",
    ),
    23: (
        """
        CREATE TABLE meshcore_observed_nodes (
            public_key_hex TEXT PRIMARY KEY
                CHECK (length(public_key_hex) = 64),
            first_seen_utc TEXT NOT NULL,
            last_seen_utc TEXT NOT NULL,
            observation_count INTEGER NOT NULL DEFAULT 0
                CHECK (observation_count >= 0),
            node_type_code INTEGER
                CHECK (node_type_code BETWEEN 0 AND 255),
            advertised_name TEXT,
            last_rssi_dbm REAL,
            last_snr_db REAL,
            receiver_latitude REAL,
            receiver_longitude REAL,
            receiver_gps_updated_at TEXT
        )
        """,
        """
        CREATE TABLE meshcore_observations (
            observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
            public_key_hex TEXT NOT NULL
                REFERENCES meshcore_observed_nodes (public_key_hex),
            event_type TEXT NOT NULL
                CHECK (event_type IN (
                    'advertisement', 'new_advertisement', 'path_updated'
                )),
            received_at_utc TEXT NOT NULL,
            peer_advert_timestamp INTEGER,
            node_type_code INTEGER,
            advertised_name TEXT,
            rssi_dbm REAL,
            snr_db REAL,
            receiver_latitude REAL,
            receiver_longitude REAL,
            receiver_gps_updated_at TEXT,
            gps_status TEXT NOT NULL,
            CHECK (
                (receiver_latitude IS NULL AND receiver_longitude IS NULL)
                OR
                (receiver_latitude BETWEEN -90 AND 90
                 AND receiver_longitude BETWEEN -180 AND 180)
            )
        )
        """,
        """
        CREATE INDEX meshcore_observations_received_idx
        ON meshcore_observations (received_at_utc DESC)
        """,
        """
        CREATE INDEX meshcore_observations_node_idx
        ON meshcore_observations (public_key_hex, received_at_utc DESC)
        """,
    ),
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
