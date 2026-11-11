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
from rolling_thunder.meshcore_passive import MeshcoreObservation
from rolling_thunder.storage import initialize_database


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
    unavailable = lambda reason: ReceiverLocation(None, None, None, reason)
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
    """Store append-only receive observations in the existing app database."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        initialize_database(database_path)

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
                    rssi_dbm, snr_dbm, receiver_latitude, receiver_longitude,
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
