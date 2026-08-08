"""Tests for the Pi-side durable Forge shared-spot cache."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from rolling_thunder.domain import Frequency, RadioMode
from rolling_thunder.forge_client import (
    ForgeRemoteProviderHealth,
    ForgeRemoteProviderStatus,
    ForgeSpotClientResult,
)
from rolling_thunder.forge_spot_cache_repository import ForgeSpotCacheRepository
from rolling_thunder.spot_domain import (
    DxSpotIdentity,
    PotaSpotIdentity,
    PotaSpotMetadata,
    SpotProvider,
    SpotRecord,
    SpotSnapshot,
    SpotSourceMetadataItem,
)
from rolling_thunder.storage import CURRENT_SCHEMA_VERSION, StorageError, initialize_database


def timestamp(minute: int) -> datetime:
    return datetime(2026, 8, 7, 12, minute, tzinfo=UTC)


def sample_result(*, revision: int = 7, received_minute: int = 1) -> ForgeSpotClientResult:
    pota_frequency = Frequency(hz=7_222_000)
    dx_frequency = Frequency(hz=14_250_000)
    spots = (
        SpotRecord(
            identity=PotaSpotIdentity(
                park_reference="US-0001",
                frequency=pota_frequency,
            ),
            callsign="KI5VNB",
            operator_name="Geoff Kline",
            grid="EM79xm",
            frequency=pota_frequency,
            mode=RadioMode.LSB,
            display_mode="SSB",
            spotted_at=timestamp(0),
            source_metadata=(
                SpotSourceMetadataItem(key="comment", value="CQ POTA"),
            ),
            pota=PotaSpotMetadata(
                park_reference="US-0001",
                park_name="Test Park",
                location_code="US-OH",
                latitude=39.1,
                longitude=-84.2,
            ),
        ),
        SpotRecord(
            identity=DxSpotIdentity(callsign="K1ABC", frequency=dx_frequency),
            callsign="K1ABC",
            operator_name="DX Operator",
            grid="FN31pr",
            frequency=dx_frequency,
            mode=RadioMode.USB,
            display_mode="SSB",
            spotted_at=timestamp(0),
            source_metadata=(
                SpotSourceMetadataItem(key="mode_source", value="fallback"),
                SpotSourceMetadataItem(key="spotter", value="W1AW"),
            ),
        ),
    )
    snapshot = SpotSnapshot(generated_at=timestamp(0), spots=spots)
    providers = (
        ForgeRemoteProviderHealth(
            provider=SpotProvider.DX,
            status=ForgeRemoteProviderStatus.HEALTHY,
            active_spot_count=1,
            last_attempt_at=timestamp(0),
            last_success_at=timestamp(0),
        ),
        ForgeRemoteProviderHealth(
            provider=SpotProvider.POTA,
            status=ForgeRemoteProviderStatus.HEALTHY,
            active_spot_count=1,
            last_attempt_at=timestamp(0),
            last_success_at=timestamp(0),
        ),
    )
    return ForgeSpotClientResult(
        snapshot_revision=revision,
        snapshot=snapshot,
        providers=providers,
        received_at=timestamp(received_minute),
    )


def test_repository_round_trips_complete_enriched_snapshot(tmp_path: Path) -> None:
    database_path = tmp_path / "rolling-thunder.db"
    repository = ForgeSpotCacheRepository(database_path)
    expected = sample_result()

    repository.replace(expected)

    assert repository.load() == expected


def test_repository_replaces_complete_snapshot(tmp_path: Path) -> None:
    database_path = tmp_path / "rolling-thunder.db"
    repository = ForgeSpotCacheRepository(database_path)
    repository.replace(sample_result())
    replacement = sample_result(revision=8, received_minute=2)

    repository.replace(replacement)

    assert repository.load() == replacement
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM forge_spot_cache").fetchone() == (2,)
        assert connection.execute(
            "SELECT COUNT(*) FROM forge_spot_cache_source_metadata"
        ).fetchone() == (3,)
        assert connection.execute(
            "SELECT COUNT(*) FROM forge_spot_cache_provider_health"
        ).fetchone() == (2,)


def test_repository_returns_none_without_cached_snapshot(tmp_path: Path) -> None:
    repository = ForgeSpotCacheRepository(tmp_path / "rolling-thunder.db")

    assert repository.load() is None


def test_repository_rejects_corrupt_stable_identity(tmp_path: Path) -> None:
    database_path = tmp_path / "rolling-thunder.db"
    repository = ForgeSpotCacheRepository(database_path)
    repository.replace(sample_result())
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE forge_spot_cache SET stable_key = 'dx:BAD:1' WHERE position = 0"
        )
        connection.commit()

    with pytest.raises(StorageError, match="stable spot identity"):
        repository.load()


def test_failed_replace_rolls_back_to_previous_snapshot(tmp_path: Path) -> None:
    database_path = tmp_path / "rolling-thunder.db"
    repository = ForgeSpotCacheRepository(database_path)
    original = sample_result()
    repository.replace(original)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_forge_spot_insert
            BEFORE INSERT ON forge_spot_cache
            BEGIN
                SELECT RAISE(ABORT, 'forced cache write failure');
            END
            """
        )
        connection.commit()

    with pytest.raises(StorageError, match="could not be replaced"):
        repository.replace(sample_result(revision=8, received_minute=2))

    assert repository.load() == original


def create_version_six_database(database_path: Path) -> None:
    """Create representative v6 data without applying the new v7 migration."""
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE schema_metadata (
                singleton_id INTEGER PRIMARY KEY,
                schema_version INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO schema_metadata VALUES (1, 6, '2026-08-07T12:00:00Z')"
        )
        connection.execute(
            "CREATE TABLE contacts (contact_id TEXT PRIMARY KEY, callsign TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO contacts VALUES ('contact-1', 'W8O')"
        )
        connection.execute(
            """
            CREATE TABLE pota_spot_cache (
                position INTEGER PRIMARY KEY,
                activator TEXT NOT NULL,
                park_reference TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO pota_spot_cache VALUES (0, 'KI5VNB', 'US-0001')"
        )
        connection.commit()


def test_schema_v7_migration_preserves_contacts_and_legacy_pota_cache(tmp_path: Path) -> None:
    database_path = tmp_path / "rolling-thunder.db"
    create_version_six_database(database_path)

    version = initialize_database(database_path)

    assert version == CURRENT_SCHEMA_VERSION == 7
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT contact_id, callsign FROM contacts"
        ).fetchall() == [("contact-1", "W8O")]
        assert connection.execute(
            "SELECT position, activator, park_reference FROM pota_spot_cache"
        ).fetchall() == [(0, "KI5VNB", "US-0001")]
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert {
        "forge_spot_cache_metadata",
        "forge_spot_cache",
        "forge_spot_cache_source_metadata",
        "forge_spot_cache_provider_health",
    }.issubset(tables)
