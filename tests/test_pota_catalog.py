"""Tests for the separate offline POTA park catalog."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from rolling_thunder.pota_catalog import (
    PotaCatalogImportError,
    import_pota_catalog_csv,
    import_pota_catalog_csvs,
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


def test_import_filters_non_us_programs(tmp_path: Path) -> None:
    source = tmp_path / "parks.csv"
    database = tmp_path / "pota-catalog.db"
    write_csv(
        source,
        "reference,name,latitude,longitude,locationDesc\n"
        "US-0001,US Park,44,-68,US-ME\n"
        "CA-0001,Canadian Park,51,-115,CA-AB\n",
    )

    result = import_pota_catalog_csv(source, database)

    assert result.park_count == 1
    with sqlite3.connect(database) as connection:
        rows = connection.execute("SELECT reference FROM parks").fetchall()
    assert rows == [("US-0001",)]


def test_multi_state_import_preserves_real_export_fields(tmp_path: Path) -> None:
    ohio = tmp_path / "ohio.csv"
    indiana = tmp_path / "indiana.csv"
    database = tmp_path / "pota-catalog.db"
    write_csv(
        ohio,
        "reference,name,latitude,longitude,grid,locationDesc,attempts,activations,"
        "qsos,website,notes,my_activations,my_hunted_qsos\n"
        "US-0732,Dayton Aviation Heritage National Historical Park,39.7999,"
        "-84.0663,EM79xt,US-OH,603,570,16370,https://www.nps.gov/daav/index.htm,"
        "Park is spread out over multiple locations.,0,0\n",
    )
    write_csv(
        indiana,
        "reference,name,latitude,longitude,grid,locationDesc\n"
        "US-9998,Indiana Example,39.8,-86.1,EM69wt,US-IN\n",
    )

    result = import_pota_catalog_csvs(
        (indiana, ohio),
        database,
        source_version="2026-09-27",
        imported_at=datetime(2026, 9, 27, 21, 0, tzinfo=UTC),
    )

    assert result.park_count == 2
    assert len(result.source_paths) == 2
    with sqlite3.connect(database) as connection:
        dayton = connection.execute(
            """
            SELECT reference, name, latitude, longitude, grid, website, notes
            FROM parks WHERE reference = 'US-0732'
            """
        ).fetchone()
        metadata = connection.execute(
            """
            SELECT schema_version, source_file_count, source_version, park_count
            FROM catalog_metadata
            """
        ).fetchone()

    assert dayton == (
        "US-0732",
        "Dayton Aviation Heritage National Historical Park",
        39.7999,
        -84.0663,
        "EM79xt",
        "https://www.nps.gov/daav/index.htm",
        "Park is spread out over multiple locations.",
    )
    assert metadata == (2, 2, "2026-09-27", 2)


def test_duplicate_reference_across_state_files_rejects_refresh(tmp_path: Path) -> None:
    ohio = tmp_path / "ohio.csv"
    indiana = tmp_path / "indiana.csv"
    database = tmp_path / "pota-catalog.db"
    header = "reference,name,latitude,longitude,grid,locationDesc\n"
    write_csv(ohio, header + "US-0732,Dayton Park,39.8,-84.1,EM79xt,US-OH\n")
    write_csv(indiana, header + "US-0732,Duplicate,40,-86,EN60aa,US-IN\n")

    with pytest.raises(PotaCatalogImportError, match="indiana.csv: invalid row 2"):
        import_pota_catalog_csvs((ohio, indiana), database)

    assert not database.exists()


def test_bad_later_state_file_preserves_last_known_good_catalog(tmp_path: Path) -> None:
    original = tmp_path / "original.csv"
    ohio = tmp_path / "ohio.csv"
    broken = tmp_path / "broken.csv"
    database = tmp_path / "pota-catalog.db"
    header = "reference,name,latitude,longitude,locationDesc\n"
    write_csv(original, header + "US-0001,Existing Park,40,-82,US-OH\n")
    import_pota_catalog_csv(original, database)
    original_database = database.read_bytes()

    write_csv(ohio, header + "US-0732,Dayton Park,39.8,-84.1,US-OH\n")
    write_csv(broken, header + "US-9999,Broken Park,999,-86,US-IN\n")

    with pytest.raises(PotaCatalogImportError, match="broken.csv: invalid row 2"):
        import_pota_catalog_csvs((ohio, broken), database)

    assert database.read_bytes() == original_database
