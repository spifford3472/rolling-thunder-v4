"""SQLite/GPS tests for the disabled passive MeshCore collector."""

import inspect
import sqlite3
from datetime import UTC, datetime, timedelta

from rolling_thunder.domain import GPSFixState, GPSPosition
from rolling_thunder.gps import GPSConnectionState, GPSState

from rolling_thunder.meshcore_observation_repository import (
    MeshcoreObservationRepository,
    receiver_location_at,
)
from rolling_thunder.meshcore_passive import parse_passive_notification
from rolling_thunder.storage import CURRENT_SCHEMA_VERSION, initialize_database

NOW = datetime(2026, 11, 11, 5, 0, tzinfo=UTC)


def _gps(
    *, age_s: float = 2.0, accuracy_m: float | None = 6.0
) -> GPSState:
    position = GPSPosition(
        fix_state=GPSFixState.THREE_DIMENSIONAL,
        latitude=39.56,
        longitude=-84.12,
        accuracy_m=accuracy_m,
        updated_at=NOW - timedelta(seconds=age_s),
    )
    return GPSState(
        connection_state=GPSConnectionState.CONNECTED,
        position=position,
        updated_at=NOW,
    )


def _event(suffix: int = 1):
    event = parse_passive_notification(
        b"\x80" + bytes(31) + bytes([suffix])
    )
    assert event is not None
    return event


def test_schema_additive_and_idempotent(tmp_path):
    path = tmp_path / "data.db"
    assert initialize_database(path) == CURRENT_SCHEMA_VERSION
    assert initialize_database(path) == CURRENT_SCHEMA_VERSION
    with sqlite3.connect(path) as connection:
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        assert {"contacts", "meshcore_observations", "meshcore_observed_nodes"} <= tables
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)


def test_observations_append_and_summary_maintains_identity(tmp_path):
    repo = MeshcoreObservationRepository(tmp_path / "data.db")
    repo.record(_event(1), NOW, _gps())
    repo.record(_event(1), NOW + timedelta(seconds=2), _gps())
    repo.record(_event(2), NOW, None)
    with sqlite3.connect(tmp_path / "data.db") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM meshcore_observations"
        ).fetchone() == (3,)
        assert sorted(row[0] for row in connection.execute(
            "SELECT observation_count FROM meshcore_observed_nodes"
        )) == [1, 2]
        assert connection.execute(
            "SELECT receiver_latitude, receiver_longitude, gps_status "
            "FROM meshcore_observations ORDER BY observation_id LIMIT 1"
        ).fetchone() == (39.56, -84.12, "gps_valid")
        assert connection.execute(
            "SELECT receiver_latitude, gps_status FROM meshcore_observations "
            "ORDER BY observation_id DESC LIMIT 1"
        ).fetchone() == (None, "gps_unavailable")


def test_stale_future_and_low_accuracy_gps_still_record(tmp_path):
    repo = MeshcoreObservationRepository(tmp_path / "data.db")
    for state, expected in (
        (_gps(age_s=11), "gps_stale"),
        (_gps(age_s=-1), "gps_future_fix"),
        (_gps(accuracy_m=200), "gps_low_accuracy"),
    ):
        repo.record(_event(), NOW, state)
        with sqlite3.connect(tmp_path / "data.db") as connection:
            assert connection.execute(
                "SELECT receiver_latitude, gps_status "
                "FROM meshcore_observations ORDER BY observation_id DESC LIMIT 1"
            ).fetchone() == (None, expected)


def test_missing_and_invalid_timestamp_handling(tmp_path):
    repo = MeshcoreObservationRepository(tmp_path / "data.db")
    assert receiver_location_at(None, NOW).status == "gps_unavailable"
    try:
        repo.record(_event(), NOW.replace(tzinfo=None), _gps())
    except ValueError:
        pass
    else:
        raise AssertionError("Expected naive receive timestamp rejection")


def test_no_runtime_or_serial_ownership():
    import rolling_thunder.meshcore_observation_repository as module
    source = inspect.getsource(module)
    assert "serial.Serial" not in source
    assert "/dev/tty" not in source
