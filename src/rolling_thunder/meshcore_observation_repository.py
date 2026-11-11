"""Dormant SQLite persistence for passive MeshCore observations.

No transport, radio, background worker or application runtime composition exists
in this module. Writing requires an explicit caller with a decoded push event.
"""

import math
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from rolling_thunder.domain import GPSFixState
from rolling_thunder.gps import GPSConnectionState, GPSState
from rolling_thunder.meshcore_passive import MeshcoreObservation, MeshcoreSignalSample

_MESHCORE_SCHEMA_VERSION = 2


def initialize_meshcore_database(database_path: Path) -> int:
    """Initialize isolated collector storage without migrating the QSO database.

    Reject databases owned by any other subsystem and unsupported future schema
    versions. Creation and metadata publication share one SQLite transaction.
    """
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database_path, timeout=5.0) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        objects = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        allowed = {
            "meshcore_schema", "meshcore_observed_nodes",
            "meshcore_observations", "meshcore_signal_samples",
        }
        if objects - allowed:
            raise ValueError("Database contains non-MeshCore tables")
        if "meshcore_schema" in objects:
            existing = connection.execute(
                "SELECT version FROM meshcore_schema WHERE id = 1"
            ).fetchone()
            if existing not in ((1,), (_MESHCORE_SCHEMA_VERSION,)):
                raise ValueError("Unsupported MeshCore database schema")
            if not {"meshcore_observed_nodes", "meshcore_observations"} <= objects:
                raise ValueError("Incomplete MeshCore database schema")
            if existing == (1,):
                # Additive v1-to-v2 migration; preserve all historical observations.
                _create_signal_table(connection)
                connection.execute(
                    "UPDATE meshcore_schema SET version = ? WHERE id = 1",
                    (_MESHCORE_SCHEMA_VERSION,),
                )
            elif "meshcore_signal_samples" not in objects:
                raise ValueError("Incomplete MeshCore database schema")
            return _MESHCORE_SCHEMA_VERSION
        if objects:
            raise ValueError("Incomplete unversioned MeshCore database")

        connection.execute("""
            CREATE TABLE meshcore_schema (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                version INTEGER NOT NULL
            )
        """)
        connection.execute("""
            CREATE TABLE meshcore_observed_nodes (
                public_key_hex TEXT PRIMARY KEY CHECK (length(public_key_hex)=64),
                first_seen_utc TEXT NOT NULL,
                last_seen_utc TEXT NOT NULL,
                observation_count INTEGER NOT NULL CHECK (observation_count >= 0),
                node_type_code INTEGER CHECK (node_type_code BETWEEN 0 AND 255),
                advertised_name TEXT,
                last_rssi_dbm REAL,
                last_snr_db REAL,
                receiver_latitude REAL,
                receiver_longitude REAL,
                receiver_gps_updated_at TEXT
            )
        """)
        connection.execute("""
            CREATE TABLE meshcore_observations (
                observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                public_key_hex TEXT NOT NULL REFERENCES meshcore_observed_nodes,
                event_type TEXT NOT NULL CHECK (
                    event_type IN (
                        'advertisement', 'new_advertisement', 'path_updated'
                    )
                ),
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
                    OR (receiver_latitude BETWEEN -90 AND 90
                        AND receiver_longitude BETWEEN -180 AND 180)
                )
            )
        """)
        connection.execute("""
            CREATE INDEX meshcore_observations_received_idx
            ON meshcore_observations(received_at_utc DESC)
        """)
        connection.execute("""
            CREATE INDEX meshcore_observations_node_idx
            ON meshcore_observations(public_key_hex, received_at_utc DESC)
        """)
        _create_signal_table(connection)
        connection.execute(
            "INSERT INTO meshcore_schema(id, version) VALUES(1, ?)",
            (_MESHCORE_SCHEMA_VERSION,),
        )
    return _MESHCORE_SCHEMA_VERSION


def _create_signal_table(connection: sqlite3.Connection) -> None:
    """Create unattributed RF metrics storage; never store the raw packet."""
    connection.execute("""
        CREATE TABLE meshcore_signal_samples (
            sample_id INTEGER PRIMARY KEY AUTOINCREMENT,
            received_at_utc TEXT NOT NULL,
            rssi_dbm REAL NOT NULL,
            snr_db REAL NOT NULL,
            receiver_latitude REAL,
            receiver_longitude REAL,
            gps_status TEXT NOT NULL,
            CHECK (rssi_dbm BETWEEN -128 AND 127),
            CHECK (snr_db BETWEEN -32 AND 31.75),
            CHECK (
                (receiver_latitude IS NULL AND receiver_longitude IS NULL)
                OR (receiver_latitude BETWEEN -90 AND 90
                    AND receiver_longitude BETWEEN -180 AND 180)
            )
        )
    """)
    connection.execute("""
        CREATE INDEX meshcore_signal_samples_received_idx
        ON meshcore_signal_samples(received_at_utc DESC)
    """)

@dataclass(frozen=True, slots=True)
class ReceiverLocation:
    """Receiver's verified, contemporaneous GPS fix or a rejection reason."""

    latitude: float | None
    longitude: float | None
    gps_updated_at: datetime | None
    status: str


def receiver_location_at(
    state: GPSState | None,
    received_at: datetime,
    *,
    max_age_s: float = 10.0,
    max_accuracy_m: float = 100.0,
) -> ReceiverLocation:
    """Read immutable Rolling Thunder GPS state; never query a serial receiver."""
    if received_at.tzinfo is None or received_at.utcoffset() is None:
        raise ValueError("received_at must be timezone-aware")
    if max_age_s <= 0 or max_accuracy_m <= 0:
        raise ValueError("Freshness limits must be positive")
    def unavailable(reason: str) -> ReceiverLocation:
        """Retain an observation without inventing receiver coordinates."""
        return ReceiverLocation(None, None, None, reason)
    if state is None or state.connection_state is not GPSConnectionState.CONNECTED:
        return unavailable("gps_unavailable")
    position = state.position
    if position is None or position.fix_state is GPSFixState.NO_FIX:
        return unavailable("gps_no_fix")
    latitude, longitude = position.latitude, position.longitude
    if (
        latitude is None or longitude is None
        or not math.isfinite(latitude) or not math.isfinite(longitude)
    ):
        return unavailable("gps_invalid")
    age = (received_at.astimezone(UTC) - position.updated_at).total_seconds()
    if age < 0:
        return unavailable("gps_future_fix")
    if age > max_age_s:
        return unavailable("gps_stale")
    if position.accuracy_m is not None and (
        not math.isfinite(position.accuracy_m)
        or position.accuracy_m > max_accuracy_m
    ):
        return unavailable("gps_low_accuracy")
    return ReceiverLocation(latitude, longitude, position.updated_at, "gps_valid")


class MeshcoreObservationRepository:
    """Store append-only observations in an isolated MeshCore-only database."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        initialize_meshcore_database(database_path)

    def record_signal(
        self,
        sample: MeshcoreSignalSample,
        received_at: datetime,
        gps_state: GPSState | None,
    ) -> int:
        """Store only RF signal metrics, without RF payload or assumed node ID."""
        if received_at.tzinfo is None or received_at.utcoffset() is None:
            raise ValueError("received_at must be timezone-aware")
        if not math.isfinite(sample.rssi_dbm) or not math.isfinite(sample.snr_db):
            raise ValueError("RF signal metrics must be finite")
        location = receiver_location_at(gps_state, received_at)
        with sqlite3.connect(self._database_path, timeout=5.0) as connection:
            cursor = connection.execute(
                """
                INSERT INTO meshcore_signal_samples (
                    received_at_utc, rssi_dbm, snr_db,
                    receiver_latitude, receiver_longitude, gps_status
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    received_at.astimezone(UTC).isoformat(),
                    sample.rssi_dbm, sample.snr_db, location.latitude,
                    location.longitude, location.status,
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("No signal sample ID returned by SQLite")
            return cursor.lastrowid

    def record(
        self,
        event: MeshcoreObservation,
        received_at: datetime,
        gps_state: GPSState | None,
    ) -> int:
        """Commit one event with receiver-local GPS; return its database ID."""
        if received_at.tzinfo is None or received_at.utcoffset() is None:
            raise ValueError("received_at must be timezone-aware")
        if len(event.public_key_hex) != 64 or any(
            char not in "0123456789abcdef" for char in event.public_key_hex
        ):
            raise ValueError("Invalid full MeshCore identity")
        location = receiver_location_at(gps_state, received_at)
        received = received_at.astimezone(UTC).isoformat()
        gps_time = (
            location.gps_updated_at.isoformat()
            if location.gps_updated_at is not None
            else None
        )
        with sqlite3.connect(self._database_path, timeout=5.0) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(
                """
                INSERT INTO meshcore_observed_nodes (
                    public_key_hex, first_seen_utc, last_seen_utc,
                    observation_count, node_type_code, advertised_name,
                    last_rssi_dbm, last_snr_db, receiver_latitude,
                    receiver_longitude, receiver_gps_updated_at
                ) VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(public_key_hex) DO UPDATE SET
                    first_seen_utc = MIN(first_seen_utc, excluded.first_seen_utc),
                    last_seen_utc = MAX(last_seen_utc, excluded.last_seen_utc),
                    observation_count = observation_count + 1,
                    node_type_code = COALESCE(
                        excluded.node_type_code, node_type_code
                    ),
                    advertised_name = COALESCE(
                        excluded.advertised_name, advertised_name
                    ),
                    last_rssi_dbm = COALESCE(excluded.last_rssi_dbm, last_rssi_dbm),
                    last_snr_db = COALESCE(excluded.last_snr_db, last_snr_db),
                    receiver_latitude = CASE
                        WHEN excluded.last_seen_utc >= last_seen_utc
                        THEN excluded.receiver_latitude ELSE receiver_latitude END,
                    receiver_longitude = CASE
                        WHEN excluded.last_seen_utc >= last_seen_utc
                        THEN excluded.receiver_longitude ELSE receiver_longitude END,
                    receiver_gps_updated_at = CASE
                        WHEN excluded.last_seen_utc >= last_seen_utc
                        THEN excluded.receiver_gps_updated_at
                        ELSE receiver_gps_updated_at END
                """,
                (
                    event.public_key_hex, received, received,
                    event.node_type_code, event.advertised_name,
                    event.rssi_dbm, event.snr_db, location.latitude,
                    location.longitude, gps_time,
                ),
            )
            cursor = connection.execute(
                """
                INSERT INTO meshcore_observations (
                    public_key_hex, event_type, received_at_utc,
                    peer_advert_timestamp, node_type_code, advertised_name,
                    rssi_dbm, snr_db, receiver_latitude, receiver_longitude,
                    receiver_gps_updated_at, gps_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.public_key_hex, event.event_type.value, received,
                    event.advertised_timestamp, event.node_type_code,
                    event.advertised_name, event.rssi_dbm, event.snr_db,
                    location.latitude, location.longitude, gps_time,
                    location.status,
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("No observation ID returned by SQLite")
            return cursor.lastrowid
