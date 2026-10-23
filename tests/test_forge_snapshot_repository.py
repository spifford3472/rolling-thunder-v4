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


def mode_spot(mode: RadioMode, position: int) -> SpotRecord:
    frequency = Frequency(hz=14_000_000 + position * 1_000)
    callsign = f"K{position + 1}ABC"
    if position % 2 == 0:
        return SpotRecord(
            identity=PotaSpotIdentity(
                callsign=callsign,
                park_reference=f"US-{position + 1:04d}",
                frequency=frequency,
            ),
            callsign=callsign,
            frequency=frequency,
            mode=mode,
            display_mode=mode.value,
            spotted_at=BASE_TIME + timedelta(seconds=position),
            pota=PotaSpotMetadata(park_reference=f"US-{position + 1:04d}"),
        )
    return SpotRecord(
        identity=DxSpotIdentity(callsign=callsign, frequency=frequency),
        callsign=callsign,
        frequency=frequency,
        mode=mode,
        display_mode=mode.value,
        spotted_at=BASE_TIME + timedelta(seconds=position),
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


def test_repository_round_trips_every_typed_mode_in_mixed_snapshot(tmp_path: Path) -> None:
    repository = SqliteForgeSnapshotRepository(tmp_path / "forge-spots.db")
    spots = tuple(mode_spot(mode, position) for position, mode in enumerate(RadioMode))
    pota = provider_slice(
        SpotProvider.POTA,
        tuple(spot for spot in spots if spot.provider is SpotProvider.POTA),
    )
    dx = provider_slice(
        SpotProvider.DX,
        tuple(spot for spot in spots if spot.provider is SpotProvider.DX),
    )
    snapshot = SpotSnapshot.from_spots(generated_at=BASE_TIME, spots=spots)

    repository.replace(snapshot, (pota, dx))
    loaded = repository.load()

    assert loaded is not None
    assert {spot.mode for spot in loaded.snapshot.spots} == set(RadioMode)
    assert loaded.snapshot == snapshot


def test_legacy_mode_constraint_migrates_without_changing_snapshot(tmp_path: Path) -> None:
    database_path = tmp_path / "forge-spots.db"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE forge_schema_metadata (
                singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                schema_version INTEGER NOT NULL CHECK (schema_version >= 1)
            );
            INSERT INTO forge_schema_metadata VALUES (1, 1);
            CREATE TABLE forge_snapshot_metadata (
                singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                revision INTEGER NOT NULL CHECK (revision >= 1),
                generated_at TEXT NOT NULL
            );
            INSERT INTO forge_snapshot_metadata
                VALUES (1, 7, '2026-08-05T20:00:00Z');
            CREATE TABLE forge_provider_slices (
                provider TEXT PRIMARY KEY CHECK (provider IN ('pota', 'dx')),
                fetched_at TEXT NOT NULL
            );
            INSERT INTO forge_provider_slices VALUES ('dx', '2026-08-05T20:00:02Z');
            CREATE TABLE forge_spots (
                position INTEGER PRIMARY KEY CHECK (position >= 0),
                provider TEXT NOT NULL,
                stable_key TEXT NOT NULL UNIQUE,
                callsign TEXT NOT NULL,
                operator_name TEXT,
                grid TEXT,
                frequency_hz INTEGER NOT NULL CHECK (frequency_hz > 0),
                mode TEXT NOT NULL
                    CHECK (mode IN ('AM', 'CW', 'DATA', 'FM', 'LSB', 'USB')),
                display_mode TEXT NOT NULL,
                spotted_at TEXT NOT NULL,
                source_metadata_json TEXT NOT NULL,
                pota_park_reference TEXT,
                pota_park_name TEXT,
                pota_location_code TEXT,
                pota_latitude REAL,
                pota_longitude REAL,
                FOREIGN KEY (provider) REFERENCES forge_provider_slices (provider)
                    ON DELETE CASCADE
            );
                INSERT INTO forge_spots VALUES (
                    0, 'dx', 'dx:K1ABC:14025000', 'K1ABC', NULL, NULL,
                    14025000, 'CW', 'CW', '2026-08-05T20:00:01Z',
                    '[{"key":"source","value":"deterministic-test"}]',
                    NULL, NULL, NULL, NULL, NULL
                );
            """
        )

    repository = SqliteForgeSnapshotRepository(database_path)
    loaded = repository.load()

    assert loaded is not None
    assert loaded.revision == 7
    assert loaded.snapshot == SpotSnapshot.from_spots(
        generated_at=BASE_TIME,
        spots=(dx_spot(),),
    )
    with sqlite3.connect(database_path) as connection:
        table_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'forge_spots'"
        ).fetchone()[0]
        indexes = connection.execute("PRAGMA index_list(forge_spots)").fetchall()
        assert "'DMR'" in table_sql and "'FT8'" in table_sql
        assert any(index[2] == 1 for index in indexes), "stable_key must remain unique"


def test_failed_mode_insert_retains_complete_last_good_snapshot(tmp_path: Path) -> None:
    database_path = tmp_path / "forge-spots.db"
    repository = SqliteForgeSnapshotRepository(database_path)
    original_dx = provider_slice(SpotProvider.DX, (dx_spot(),))
    original = SpotSnapshot.from_spots(generated_at=BASE_TIME, spots=original_dx.spots)
    stored = repository.replace(original, (original_dx,))
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_dmr BEFORE INSERT ON forge_spots
            WHEN NEW.mode = 'DMR'
            BEGIN
                SELECT RAISE(ABORT, 'deterministic mode rejection');
            END
            """
        )

    dmr = mode_spot(RadioMode.DMR, 0)
    replacement_pota = provider_slice(SpotProvider.POTA, (dmr,))
    replacement = SpotSnapshot.from_spots(
        generated_at=BASE_TIME + timedelta(minutes=1),
        spots=(dmr,),
    )
    with pytest.raises(ForgeSnapshotStorageError, match="deterministic mode rejection"):
        repository.replace(replacement, (replacement_pota,))

    assert repository.load() == stored


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
