"""Tests for mutable operator preferences in application SQLite."""

import sqlite3
from concurrent.futures import Executor, Future
from pathlib import Path
from typing import Any

import pytest

from rolling_thunder.operator_preferences import (
    OperatorPreferenceRepository,
    OperatorPreferenceService,
)
from rolling_thunder.storage import CURRENT_SCHEMA_VERSION, initialize_database


class ImmediateExecutor(Executor):
    def submit(
        self,
        function: Any,
        /,
        *args: Any,
        **kwargs: Any,
    ) -> Future[Any]:
        future: Future[Any] = Future()
        future.set_result(function(*args, **kwargs))
        return future


def test_schema_migration_creates_operator_preferences_table(tmp_path: Path) -> None:
    database_path = tmp_path / "rolling-thunder.db"
    initialize_database(database_path)

    with sqlite3.connect(database_path) as connection:
        connection.execute("DROP TABLE pota_worked_markers")
        connection.execute("DROP TABLE repeater_active_overrides")
        connection.execute(
            "DROP TABLE weather_alert_notification_ledger"
        )
        connection.execute("DROP TABLE forge_weather_alert_cache")
        connection.execute("DROP TABLE forge_weather_cache")
        connection.execute("DROP TABLE operator_preferences")
        connection.execute(
            "UPDATE schema_metadata SET schema_version = 7 WHERE singleton_id = 1"
        )
        connection.commit()

    assert initialize_database(database_path) == CURRENT_SCHEMA_VERSION

    with sqlite3.connect(database_path) as connection:
        columns = connection.execute(
            "PRAGMA table_info(operator_preferences)"
        ).fetchall()

    assert {str(row[1]) for row in columns} == {
        "preference_key",
        "preference_value",
        "updated_at",
    }


def test_map_zoom_round_trips_through_shared_application_database(tmp_path: Path) -> None:
    database_path = tmp_path / "rolling-thunder.db"
    repository = OperatorPreferenceRepository(database_path)

    assert repository.read_map_zoom() is None

    repository.write_map_zoom(13)

    assert OperatorPreferenceRepository(database_path).read_map_zoom() == 13


def test_radar_image_choice_round_trips_through_shared_application_database(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "rolling-thunder.db"
    repository = OperatorPreferenceRepository(database_path)

    assert repository.read_radar_image_enabled() is None

    repository.write_radar_image_enabled(False)
    assert OperatorPreferenceRepository(database_path).read_radar_image_enabled() is False

    repository.write_radar_image_enabled(True)
    assert OperatorPreferenceRepository(database_path).read_radar_image_enabled() is True


def test_malformed_radar_image_choice_falls_back_as_missing(tmp_path: Path) -> None:
    database_path = tmp_path / "rolling-thunder.db"
    repository = OperatorPreferenceRepository(database_path)

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "INSERT INTO operator_preferences (preference_key, preference_value) VALUES (?, ?)",
            ("radar.image.enabled", "maybe"),
        )
        connection.commit()

    assert repository.read_radar_image_enabled() is None


def test_malformed_or_out_of_range_map_zoom_falls_back_as_missing(tmp_path: Path) -> None:
    database_path = tmp_path / "rolling-thunder.db"
    repository = OperatorPreferenceRepository(database_path)

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "INSERT INTO operator_preferences (preference_key, preference_value) VALUES (?, ?)",
            ("map.zoom", "not-an-int"),
        )
        connection.commit()

    assert repository.read_map_zoom() is None

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE operator_preferences SET preference_value = ? WHERE preference_key = ?",
            ("5", "map.zoom"),
        )
        connection.commit()

    assert repository.read_map_zoom() is None

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE operator_preferences SET preference_value = ? WHERE preference_key = ?",
            ("99", "map.zoom"),
        )
        connection.commit()

    assert repository.read_map_zoom() is None


def test_repository_rejects_map_zoom_below_operator_floor(tmp_path: Path) -> None:
    repository = OperatorPreferenceRepository(tmp_path / "rolling-thunder.db")

    with pytest.raises(ValueError, match="between 6 and 22"):
        repository.write_map_zoom(5)


def test_preference_service_submits_zoom_write_without_changing_api_contract(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "rolling-thunder.db"
    repository = OperatorPreferenceRepository(database_path)
    service = OperatorPreferenceService(repository, executor=ImmediateExecutor())

    assert service.persist_map_zoom(11) is True
    assert repository.read_map_zoom() == 11
    assert service.last_error is None


def test_preference_service_submits_radar_image_write_nonblocking(tmp_path: Path) -> None:
    database_path = tmp_path / "rolling-thunder.db"
    repository = OperatorPreferenceRepository(database_path)
    service = OperatorPreferenceService(repository, executor=ImmediateExecutor())

    assert service.persist_radar_image_enabled(False) is True
    assert repository.read_radar_image_enabled() is False
    assert service.last_error is None



def test_callsign_info_choice_round_trips_through_shared_application_database(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "rolling-thunder.db"
    repository = OperatorPreferenceRepository(database_path)

    assert repository.read_callsign_info_enabled() is None

    repository.write_callsign_info_enabled(False)
    assert OperatorPreferenceRepository(database_path).read_callsign_info_enabled() is False

    repository.write_callsign_info_enabled(True)
    assert OperatorPreferenceRepository(database_path).read_callsign_info_enabled() is True


def test_preference_service_submits_callsign_info_write_nonblocking(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "rolling-thunder.db"
    repository = OperatorPreferenceRepository(database_path)
    service = OperatorPreferenceService(repository, executor=ImmediateExecutor())

    assert service.persist_callsign_info_enabled(False) is True
    assert repository.read_callsign_info_enabled() is False
    assert service.last_error is None
