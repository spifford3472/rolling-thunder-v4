"""Tests for background POTA catalog map-marker queries and projection."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from rolling_thunder.live_map import GeoPoint
from rolling_thunder.map_tiles import build_map_viewport
from rolling_thunder.pota_map_markers import (
    PotaMapMarker,
    PotaMapMarkerService,
    project_pota_marker,
)


class ImmediateExecutor:
    def submit(self, fn, *args):
        fn(*args)


def make_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE parks (
                reference TEXT NOT NULL,
                location_code TEXT NOT NULL,
                name TEXT NOT NULL,
                program TEXT NOT NULL,
                status TEXT NOT NULL,
                park_type TEXT,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                grid TEXT,
                website TEXT,
                notes TEXT,
                PRIMARY KEY (reference, location_code)
            );
            CREATE INDEX parks_latitude_index ON parks(latitude);
            CREATE INDEX parks_longitude_index ON parks(longitude);
            """
        )
        connection.executemany(
            """
            INSERT INTO parks (
                reference, location_code, name, program, status,
                latitude, longitude
            ) VALUES (?, ?, ?, 'US', ?, ?, ?)
            """,
            (
                ("US-0001", "US-OH", "Visible Park", "active", 39.53, -84.08),
                ("US-0002", "US-OH", "Far Park", "active", 41.5, -81.7),
                ("US-0003", "US-OH", "Inactive Park", "inactive", 39.531, -84.081),
            ),
        )


def test_viewport_query_returns_only_visible_active_parks(tmp_path: Path) -> None:
    database = tmp_path / "pota-catalog.db"
    make_database(database)
    service = PotaMapMarkerService(
        database,
        clock=lambda: datetime(2026, 9, 27, tzinfo=UTC),
        executor=ImmediateExecutor(),
    )
    viewport = build_map_viewport(
        GeoPoint(39.53, -84.08),
        zoom=14,
        width_px=1200,
        height_px=800,
    )

    service.start()
    service.request_viewport(viewport)

    assert tuple(marker.reference for marker in service.latest_state.markers) == ("US-0001",)
    assert service.latest_state.viewport == viewport


def test_duplicate_multi_location_occurrence_draws_one_marker(tmp_path: Path) -> None:
    database = tmp_path / "pota-catalog.db"
    make_database(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO parks (
                reference, location_code, name, program, status,
                latitude, longitude
            ) VALUES ('US-0001', 'US-IN', 'Visible Park', 'US', 'active', 39.53, -84.08)
            """
        )
    service = PotaMapMarkerService(database, executor=ImmediateExecutor())
    viewport = build_map_viewport(
        GeoPoint(39.53, -84.08), zoom=14, width_px=1200, height_px=800
    )

    service.start()
    service.request_viewport(viewport)

    assert len(service.latest_state.markers) == 1


def test_projection_places_center_coordinate_at_viewport_center() -> None:
    viewport = build_map_viewport(
        GeoPoint(39.53, -84.08),
        zoom=15,
        width_px=1000,
        height_px=600,
    )
    placement = project_pota_marker(
        PotaMapMarker("US-1940", "Example Park", 39.53, -84.08),
        viewport,
    )

    assert placement.x_px == pytest.approx(500.0)
    assert placement.y_px == pytest.approx(300.0)


def test_request_before_start_performs_no_database_io(tmp_path: Path) -> None:
    service = PotaMapMarkerService(tmp_path / "missing.db", executor=ImmediateExecutor())
    viewport = build_map_viewport(
        GeoPoint(39.53, -84.08), zoom=14, width_px=800, height_px=600
    )

    service.request_viewport(viewport)

    assert service.latest_state.viewport is None


def test_clear_invalidates_visible_markers_without_database_work(tmp_path: Path) -> None:
    database = tmp_path / "pota-catalog.db"
    make_database(database)
    service = PotaMapMarkerService(database, executor=ImmediateExecutor())
    viewport = build_map_viewport(
        GeoPoint(39.53, -84.08), zoom=14, width_px=1200, height_px=800
    )
    service.start()
    service.request_viewport(viewport)
    assert service.latest_state.markers

    service.clear()

    assert service.latest_state.viewport is None
    assert service.latest_state.markers == ()
    assert service.latest_state.detail == "POTA MARKERS WAITING FOR CURRENT GPS"
