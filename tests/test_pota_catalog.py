"""Tests for the separate offline POTA park catalog."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from rolling_thunder.pota_catalog import (
    PotaCatalogImportError,
    import_pota_catalog_csv,
)


def write_csv(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


def test_import_creates_normalized_catalog_and_metadata(tmp_path: Path) -> None:
    source = tmp_path / "parks.csv"
    database = tmp_path / "pota-catalog.db"
    write_csv(
        source,
        "reference,name,latitude,longitude,locationDesc,status,parktype\n"
        'US-0001,Acadia,44.31,-68.2034,"US-ME",Active,National Park\n'
        'US-9999,Example Trail,39.5,-84.2,"US-OH,US-IN",Inactive,Trail\n',
    )

    result = import_pota_catalog_csv(
        source,
        database,
        source_version="2026-09-27",
        imported_at=datetime(2026, 9, 27, 20, 0, tzinfo=UTC),
    )

    assert result.park_count == 2
    with sqlite3.connect(database) as connection:
        parks = connection.execute(
            "SELECT reference, name, program, status FROM parks ORDER BY reference"
        ).fetchall()
        locations = connection.execute(
            "SELECT park_reference, location_code FROM park_locations ORDER BY 1, 2"
        ).fetchall()
        metadata = connection.execute(
            "SELECT source_version, park_count FROM catalog_metadata"
        ).fetchone()

    assert parks == [
        ("US-0001", "Acadia", "US", "active"),
        ("US-9999", "Example Trail", "US", "inactive"),
    ]
    assert locations == [
        ("US-0001", "US-ME"),
        ("US-9999", "US-IN"),
        ("US-9999", "US-OH"),
    ]
    assert metadata == ("2026-09-27", 2)


def test_reimport_atomically_replaces_prior_catalog(tmp_path: Path) -> None:
    source = tmp_path / "parks.csv"
    database = tmp_path / "pota-catalog.db"
    write_csv(
        source,
        "reference,name,latitude,longitude,locationDesc\n"
        "US-0001,Old Park,44,-68,US-ME\n",
    )
    import_pota_catalog_csv(source, database)

    write_csv(
        source,
        "reference,name,latitude,longitude,locationDesc\n"
        "US-0002,New Park,40,-82,US-OH\n",
    )
    import_pota_catalog_csv(source, database)

    with sqlite3.connect(database) as connection:
        rows = connection.execute("SELECT reference FROM parks").fetchall()
    assert rows == [("US-0002",)]


def test_invalid_refresh_preserves_last_known_good_catalog(tmp_path: Path) -> None:
    source = tmp_path / "parks.csv"
    database = tmp_path / "pota-catalog.db"
    write_csv(
        source,
        "reference,name,latitude,longitude,locationDesc\n"
        "US-0001,Good Park,44,-68,US-ME\n",
    )
    import_pota_catalog_csv(source, database)
    original = database.read_bytes()

    write_csv(
        source,
        "reference,name,latitude,longitude,locationDesc\n"
        "US-0002,Bad Park,999,-82,US-OH\n",
    )
    with pytest.raises(PotaCatalogImportError, match="row 2"):
        import_pota_catalog_csv(source, database)

    assert database.read_bytes() == original


def test_duplicate_reference_rejects_entire_refresh(tmp_path: Path) -> None:
    source = tmp_path / "parks.csv"
    database = tmp_path / "pota-catalog.db"
    write_csv(
        source,
        "reference,name,latitude,longitude,locationDesc\n"
        "US-0001,One,44,-68,US-ME\n"
        "US-0001,Duplicate,40,-82,US-OH\n",
    )

    with pytest.raises(PotaCatalogImportError, match="row 3"):
        import_pota_catalog_csv(source, database)
    assert not database.exists()


def test_missing_required_header_is_actionable(tmp_path: Path) -> None:
    source = tmp_path / "parks.csv"
    database = tmp_path / "pota-catalog.db"
    write_csv(source, "reference,name,latitude,longitude\nUS-0001,A,44,-68\n")

    with pytest.raises(PotaCatalogImportError, match="locations"):
        import_pota_catalog_csv(source, database)
