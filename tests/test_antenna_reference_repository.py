"""Migration, preservation, and SQLite repository tests for antenna reference v1."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import UUID

import pytest

import rolling_thunder.storage as storage_module
from rolling_thunder.antenna_reference_domain import (
    AntennaCatalogEntry,
    AntennaInstallation,
    BandAssociation,
    ExposureScenario,
    FrequencyRegion,
    FrequencySegment,
    GainSegment,
    GainUnit,
    InstallationBandAssignment,
    LossSegment,
    ModeProfile,
    TextProvenance,
)
from rolling_thunder.antenna_reference_repository import AntennaReferenceRepository
from rolling_thunder.antenna_reference_service import AntennaReferenceService
from rolling_thunder.domain import Frequency
from rolling_thunder.storage import StorageError

SOURCE = TextProvenance(source="bench record", notes="test provenance")
ANTENNA_ID = UUID("10000000-0000-0000-0000-000000000001")
BAND_ID = UUID("10000000-0000-0000-0000-000000000002")
INSTALLATION_ID = UUID("10000000-0000-0000-0000-000000000003")
MODE_ID = UUID("10000000-0000-0000-0000-000000000004")
SCENARIO_ID = UUID("10000000-0000-0000-0000-000000000005")


def aggregate() -> tuple[AntennaCatalogEntry, AntennaInstallation, ModeProfile, ExposureScenario]:
    frequencies = FrequencySegment(
        lower=Frequency(hz=50_000_000), upper=Frequency(hz=54_000_000)
    )
    catalog = AntennaCatalogEntry(
        antenna_id=ANTENNA_ID,
        name="Tomorrow antenna placeholder",
        manufacturer="Pending",
        model="Pending",
        provenance=SOURCE,
        bands=(
            BandAssociation(
                association_id=BAND_ID,
                label="6 m",
                region=FrequencyRegion.VHF,
                frequencies=frequencies,
                provenance=SOURCE,
            ),
        ),
        gains=(
            GainSegment(
                gain_id=UUID("10000000-0000-0000-0000-000000000006"),
                frequencies=frequencies,
                gain_db=2.0,
                unit=GainUnit.DBI,
                provenance=SOURCE,
            ),
        ),
    )
    installation = AntennaInstallation(
        installation_id=INSTALLATION_ID,
        antenna_id=ANTENNA_ID,
        name="Vehicle installation",
        location_description="Geometry pending measurement",
        losses_complete=True,
        loss_segments=(
            LossSegment(
                loss_id=UUID("10000000-0000-0000-0000-000000000007"),
                name="Measured path loss",
                frequencies=frequencies,
                loss_db=1.25,
                provenance=SOURCE,
            ),
        ),
        band_assignments=(
            InstallationBandAssignment(
                assignment_id=UUID("10000000-0000-0000-0000-000000000008"),
                association_id=BAND_ID,
                active=True,
                provenance=SOURCE,
            ),
        ),
        provenance=SOURCE,
    )
    mode = ModeProfile(
        mode_profile_id=MODE_ID,
        name="6 m FM",
        rf_envelope_duty=1.0,
        provenance=SOURCE,
    )
    scenario = ExposureScenario(
        scenario_id=SCENARIO_ID,
        installation_id=INSTALLATION_ID,
        mode_profile_id=MODE_ID,
        name="Six-foot placeholder",
        frequency=Frequency(hz=52_525_000),
        forward_tx_watts=50,
        controlled_tx_fraction=0.25,
        uncontrolled_tx_fraction=0.10,
        provenance=SOURCE,
    )
    return catalog, installation, mode, scenario


def test_schema_21_is_additive_and_preserves_existing_contact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "rolling-thunder.db"
    monkeypatch.setattr(storage_module, "CURRENT_SCHEMA_VERSION", 20)
    storage_module.initialize_database(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """INSERT INTO contacts (
                   contact_id, callsign, frequency_hz, mode, started_at,
                   rst_sent, rst_received, synchronization_state
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "10000000-0000-0000-0000-000000000099",
                "W8O",
                52_525_000,
                "FM",
                "2026-10-12T12:00:00Z",
                "59",
                "59",
                "pending",
            ),
        )
    monkeypatch.setattr(storage_module, "CURRENT_SCHEMA_VERSION", 21)

    assert storage_module.initialize_database(database_path) == 21
    with sqlite3.connect(database_path) as connection:
        version = connection.execute(
            "SELECT schema_version FROM schema_metadata WHERE singleton_id=1"
        ).fetchone()
        contact = connection.execute("SELECT callsign FROM contacts").fetchone()
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'antenna_%'"
            )
        }
    assert version == (21,)
    assert contact == ("W8O",)
    assert {
        "antenna_catalog",
        "antenna_band_associations",
        "antenna_gain_segments",
        "antenna_installations",
        "antenna_loss_segments",
        "antenna_installation_band_assignments",
        "antenna_mode_profiles",
    }.issubset(tables)


def test_schema_21_failure_rolls_back_whole_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "rolling-thunder.db"
    monkeypatch.setattr(storage_module, "CURRENT_SCHEMA_VERSION", 20)
    storage_module.initialize_database(database_path)
    monkeypatch.setattr(storage_module, "CURRENT_SCHEMA_VERSION", 21)
    monkeypatch.setitem(
        storage_module._MIGRATIONS,
        21,
        (
            "CREATE TABLE migration_should_rollback (value TEXT)",
            "THIS IS NOT VALID SQL",
        ),
    )

    with pytest.raises(StorageError):
        storage_module.initialize_database(database_path)

    with sqlite3.connect(database_path) as connection:
        version = connection.execute(
            "SELECT schema_version FROM schema_metadata WHERE singleton_id=1"
        ).fetchone()
        partial = connection.execute(
            "SELECT name FROM sqlite_master WHERE name='migration_should_rollback'"
        ).fetchone()
    assert version == (20,)
    assert partial is None


def test_repository_round_trip_and_service_evaluation(tmp_path: Path) -> None:
    repository = AntennaReferenceRepository(tmp_path / "rolling-thunder.db")
    catalog, installation, mode, scenario = aggregate()

    repository.save_catalog(catalog)
    repository.save_installation(installation)
    repository.save_mode_profile(mode)
    repository.save_scenario(scenario)

    assert repository.get_catalog(ANTENNA_ID) == catalog
    assert repository.list_catalog() == (catalog,)
    assert repository.get_installation(INSTALLATION_ID) == installation
    assert repository.get_mode_profile(MODE_ID) == mode
    assert repository.get_scenario(SCENARIO_ID) == scenario

    result = AntennaReferenceService(repository).evaluate_scenario(SCENARIO_ID)
    assert result.inputs_complete is True
    assert result.controlled is not None
    assert result.uncontrolled is not None
    assert result.needs_further_evaluation is True


def test_repository_does_not_seed_user_specific_reference_data(tmp_path: Path) -> None:
    database_path = tmp_path / "rolling-thunder.db"
    AntennaReferenceRepository(database_path)
    with sqlite3.connect(database_path) as connection:
        counts = tuple(
            connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "antenna_catalog",
                "antenna_installations",
                "antenna_mode_profiles",
                "rf_exposure_scenarios",
            )
        )
    assert counts == (0, 0, 0, 0)


def test_installation_rejects_band_assignment_owned_by_another_antenna(
    tmp_path: Path,
) -> None:
    repository = AntennaReferenceRepository(tmp_path / "rolling-thunder.db")
    catalog, installation, _, _ = aggregate()
    repository.save_catalog(catalog)
    wrong = installation.model_copy(
        update={"antenna_id": UUID("20000000-0000-0000-0000-000000000001")}
    )
    with pytest.raises(StorageError, match="does not belong"):
        repository.save_installation(wrong)
