"""Collector schema-2 analytics, trust, and read-only regression coverage."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from rolling_thunder.meshcore_network_analytics import MeshcoreNetworkAnalytics
from rolling_thunder.meshcore_observation_repository import (
    initialize_meshcore_database,
)

START = datetime(2026, 11, 11, 14, 0, tzinfo=UTC)
KEY_A = "a" * 64
KEY_B = "b" * 64


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = tmp_path / "meshcore.db"
    assert initialize_meshcore_database(path) == 2
    first = START.isoformat()
    later = (START + timedelta(minutes=10)).isoformat()
    outside = (START + timedelta(hours=2)).isoformat()
    with sqlite3.connect(path) as connection:
        for key, seen, role in ((KEY_A, first, 2), (KEY_B, later, None)):
            connection.execute(
                "INSERT INTO meshcore_observed_nodes "
                "(public_key_hex, first_seen_utc, last_seen_utc,"
                " observation_count, node_type_code) VALUES(?, ?, ?, ?, ?)",
                (key, seen, seen, 1, role),
            )
        for key, when, lat, lon in (
            (KEY_A, first, 39.54, -84.10),
            (KEY_A, later, 39.5401, -84.1001),
            (KEY_B, later, None, None),
            (KEY_B, outside, 39.65, -84.3),
        ):
            connection.execute(
                "INSERT INTO meshcore_observations "
                "(public_key_hex, event_type, received_at_utc,"
                "receiver_latitude, receiver_longitude, gps_status)"
                "VALUES (?, 'advertisement', ?, ?, ?, ?)",
                (key, when, lat, lon, "gps_valid" if lat else "gps_unavailable"),
            )
        connection.execute(
            "INSERT INTO meshcore_signal_samples "
            "(received_at_utc, rssi_dbm, snr_db, receiver_latitude,"
            "receiver_longitude, gps_status) VALUES (?, -82, 7.5, ?, ?, ?)",
            (later, 39.54, -84.1, "gps_valid"),
        )
    return path


def test_time_window_counts_and_roles(database: Path) -> None:
    result = MeshcoreNetworkAnalytics(database).summarize(
        START, START + timedelta(hours=1)
    )
    assert result.distinct_nodes == 2
    assert result.distinct_repeaters_latest_role == 1
    assert result.first_seen_nodes == 2
    assert result.advertisement_events == 3
    assert result.signal_samples == 1


def test_cells_are_receiver_observation_locations(database: Path) -> None:
    result = MeshcoreNetworkAnalytics(database).summarize(
        START, START + timedelta(hours=1)
    )
    assert len(result.receiver_cells) == 1
    cell = result.receiver_cells[0]
    assert (cell.latitude_bin, cell.longitude_bin) == (39.54, -84.1)
    assert cell.observations == 2
    assert cell.signal_samples == 1


def test_other_window_has_no_conflated_samples(database: Path) -> None:
    result = MeshcoreNetworkAnalytics(database).summarize(
        START + timedelta(hours=1), START + timedelta(hours=3)
    )
    assert result.distinct_nodes == 1
    assert result.advertisement_events == 1
    assert result.first_seen_nodes == 0
    assert result.signal_samples == 0


def test_read_only_does_not_change_database(database: Path) -> None:
    before = database.read_bytes()
    MeshcoreNetworkAnalytics(database).summarize(
        START, START + timedelta(hours=1)
    )
    assert before == database.read_bytes()


@pytest.mark.parametrize(
    "start, end",
    [
        (START, START),
        (START + timedelta(seconds=1), START),
        (START, START + timedelta(days=32)),
        (START.replace(tzinfo=None), START + timedelta(hours=1)),
    ],
)
def test_invalid_windows_fail_closed(
    database: Path, start: datetime, end: datetime
) -> None:
    with pytest.raises(ValueError):
        MeshcoreNetworkAnalytics(database).summarize(start, end)


def test_nonexistent_database_never_created(tmp_path: Path) -> None:
    path = tmp_path / "missing.db"
    with pytest.raises(sqlite3.OperationalError):
        MeshcoreNetworkAnalytics(path).summarize(
            START, START + timedelta(hours=1)
        )
    assert not path.exists()


def test_non_meshcore_schema_rejected(tmp_path: Path) -> None:
    path = tmp_path / "unrelated.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE unrelated (id INTEGER)")
    with pytest.raises(sqlite3.OperationalError):
        MeshcoreNetworkAnalytics(path).summarize(
            START, START + timedelta(hours=1)
        )


@pytest.mark.parametrize("limit", [0, -1, 201])
def test_unbounded_cell_limit_rejected(database: Path, limit: int) -> None:
    with pytest.raises(ValueError):
        MeshcoreNetworkAnalytics(database).summarize(
            START, START + timedelta(hours=1), maximum_cells=limit
        )
