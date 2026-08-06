"""Tests for dedicated transactional Forge snapshot persistence."""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from rolling_thunder.domain import Frequency, RadioMode
from rolling_thunder.forge_snapshot_repository import (
    ForgeSnapshotStorageError,
    SqliteForgeSnapshotRepository,
)
from rolling_thunder.forge_spot_provider import ForgeProviderSlice
from rolling_thunder.spot_domain import (
    DxSpotIdentity,
    PotaSpotIdentity,
    PotaSpotMetadata,
    SpotProvider,
    SpotRecord,
    SpotSnapshot,
    SpotSourceMetadataItem,
)

BASE_TIME = datetime(2026, 8, 5, 20, 0, tzinfo=UTC)


def pota_spot() -> SpotRecord:
    frequency = Frequency(hz=14_250_000)
    return SpotRecord(
        identity=PotaSpotIdentity(
            park_reference="US-1234",
            frequency=frequency,
        ),
        callsign="KI5VNB",
        operator_name="Geoff Kline",
        grid="EM79xm",
        frequency=frequency,
        mode=RadioMode.USB,
        display_mode="SSB",
        spotted_at=BASE_TIME,
        source_metadata=(
            SpotSourceMetadataItem(key="comments", value="Portable activation"),
        ),
        pota=PotaSpotMetadata(
            park_reference="US-1234",
            park_name="Example State Park",
            location_code="US-OH",
            latitude=39.75,
            longitude=-84.2,
        ),
    )


def dx_spot() -> SpotRecord:
    frequency = Frequency(hz=14_025_000)
    return SpotRecord(
        identity=DxSpotIdentity(callsign="K1ABC", frequency=frequency),
        callsign="K1ABC",
        frequency=frequency,
        mode=RadioMode.CW,
        display_mode="CW",
        spotted_at=BASE_TIME + timedelta(seconds=1),
        source_metadata=(
            SpotSourceMetadataItem(key="source", value="deterministic-test"),
        ),
    )


def provider_slice(
    provider: SpotProvider,
    spots: tuple[SpotRecord, ...],
    *,
    fetched_at: datetime = BASE_TIME + timedelta(seconds=2),
) -> ForgeProviderSlice:
    return ForgeProviderSlice.from_spots(
        provider=provider,
        fetched_at=fetched_at,
        spots=spots,
    )


def test_repository_round_trips_complete_multi_provider_snapshot(tmp_path: Path) -> None:
    repository = SqliteForgeSnapshotRepository(tmp_path / "forge-spots.db")
    pota = provider_slice(SpotProvider.POTA, (pota_spot(),))
    dx = provider_slice(SpotProvider.DX, (dx_spot(),))
    snapshot = SpotSnapshot.from_spots(
        generated_at=BASE_TIME + timedelta(seconds=3),
        spots=(*pota.spots, *dx.spots),
    )

    stored = repository.replace(snapshot, (pota, dx))
    loaded = repository.load()

    assert stored.revision == 1
    assert stored.snapshot == snapshot
    assert loaded == stored
    assert loaded is not None
    assert loaded.provider_slices == (dx, pota)
    assert loaded.snapshot.spots[0] == dx_spot()
    assert loaded.snapshot.spots[1] == pota_spot()


def test_replace_increments_revision_and_removes_previous_rows(tmp_path: Path) -> None:
    repository = SqliteForgeSnapshotRepository(tmp_path / "forge-spots.db")
    pota = provider_slice(SpotProvider.POTA, (pota_spot(),))
    first = SpotSnapshot.from_spots(
        generated_at=BASE_TIME,
        spots=pota.spots,
    )
    repository.replace(first, (pota,))

    empty_pota = provider_slice(
        SpotProvider.POTA,
        (),
        fetched_at=BASE_TIME + timedelta(minutes=1),
    )
    second = SpotSnapshot.empty(generated_at=BASE_TIME + timedelta(minutes=1))
    stored = repository.replace(second, (empty_pota,))
    loaded = repository.load()

    assert stored.revision == 2
    assert loaded == stored
    assert loaded is not None
    assert loaded.snapshot.spots == ()
    assert loaded.provider_slices == (empty_pota,)

    with sqlite3.connect(tmp_path / "forge-spots.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM forge_spots").fetchone() == (0,)


def test_repository_load_revalidates_stable_identity(tmp_path: Path) -> None:
    database_path = tmp_path / "forge-spots.db"
    repository = SqliteForgeSnapshotRepository(database_path)
    pota = provider_slice(SpotProvider.POTA, (pota_spot(),))
    snapshot = SpotSnapshot.from_spots(generated_at=BASE_TIME, spots=pota.spots)
    repository.replace(snapshot, (pota,))

    with sqlite3.connect(database_path) as connection:
        connection.execute("UPDATE forge_spots SET stable_key = 'pota:US-9999:1'")
        connection.commit()

    with pytest.raises(ForgeSnapshotStorageError, match="stable identity"):
        repository.load()


def test_repository_rejects_malformed_source_metadata(tmp_path: Path) -> None:
    database_path = tmp_path / "forge-spots.db"
    repository = SqliteForgeSnapshotRepository(database_path)
    pota = provider_slice(SpotProvider.POTA, (pota_spot(),))
    snapshot = SpotSnapshot.from_spots(generated_at=BASE_TIME, spots=pota.spots)
    repository.replace(snapshot, (pota,))

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE forge_spots SET source_metadata_json = ?",
            (json.dumps({"not": "an array"}),),
        )
        connection.commit()

    with pytest.raises(ForgeSnapshotStorageError, match="JSON array"):
        repository.load()


def test_repository_rejects_partial_pota_coordinates_on_load(tmp_path: Path) -> None:
    database_path = tmp_path / "forge-spots.db"
    repository = SqliteForgeSnapshotRepository(database_path)
    pota = provider_slice(SpotProvider.POTA, (pota_spot(),))
    snapshot = SpotSnapshot.from_spots(generated_at=BASE_TIME, spots=pota.spots)
    repository.replace(snapshot, (pota,))

    with sqlite3.connect(database_path) as connection:
        connection.execute("UPDATE forge_spots SET pota_longitude = NULL")
        connection.commit()

    with pytest.raises(ForgeSnapshotStorageError, match="both be provided"):
        repository.load()


def test_repository_refuses_pi_application_database(tmp_path: Path) -> None:
    database_path = tmp_path / "rolling-thunder.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE schema_metadata (singleton_id INTEGER)")
        connection.execute("CREATE TABLE contacts (contact_id TEXT)")
        connection.commit()

    with pytest.raises(
        ForgeSnapshotStorageError,
        match="separate Forge database path",
    ):
        SqliteForgeSnapshotRepository(database_path)


def test_repository_rejects_unsupported_schema_version(tmp_path: Path) -> None:
    database_path = tmp_path / "forge-spots.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE forge_schema_metadata (
                singleton_id INTEGER PRIMARY KEY,
                schema_version INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO forge_schema_metadata VALUES (1, 99)"
        )
        connection.commit()

    with pytest.raises(ForgeSnapshotStorageError, match="Unsupported"):
        SqliteForgeSnapshotRepository(database_path)
