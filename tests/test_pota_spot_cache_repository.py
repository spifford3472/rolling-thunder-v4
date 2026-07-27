import sqlite3
from datetime import UTC, datetime

import pytest

from rolling_thunder.domain import Frequency, RadioMode
from rolling_thunder.pota_spot_cache_repository import (
    PotaSpotCacheRepository,
)
from rolling_thunder.pota_spots import ParkReference, PotaSpot
from rolling_thunder.storage import StorageError

SUCCESS_AT = datetime(2026, 7, 27, 3, 0, tzinfo=UTC)


def spot(
    callsign: str = "KI5VNB",
    reference: str = "US-1234",
) -> PotaSpot:
    return PotaSpot(
        activator=callsign,
        park=ParkReference(
            reference=reference,
            name="Test Park",
        ),
        frequency=Frequency(hz=14_250_000),
        mode=RadioMode.USB,
        spotted_at=SUCCESS_AT,
        comments="test spot",
    )


def test_missing_cache_returns_none(tmp_path) -> None:
    repository = PotaSpotCacheRepository(tmp_path / "contacts.sqlite3")

    assert repository.load() is None


def test_replace_and_load_snapshot(tmp_path) -> None:
    repository = PotaSpotCacheRepository(tmp_path / "contacts.sqlite3")
    expected = (spot(),)

    repository.replace(expected, SUCCESS_AT)
    loaded = repository.load()

    assert loaded is not None
    assert loaded.spots == expected
    assert loaded.last_success_at == SUCCESS_AT


def test_replace_preserves_spot_order(tmp_path) -> None:
    repository = PotaSpotCacheRepository(tmp_path / "contacts.sqlite3")
    expected = (
        spot("KI5VNB", "US-1234"),
        spot("W8ABC", "US-5678"),
    )

    repository.replace(expected, SUCCESS_AT)

    loaded = repository.load()

    assert loaded is not None
    assert loaded.spots == expected


def test_replace_removes_previous_snapshot(tmp_path) -> None:
    repository = PotaSpotCacheRepository(tmp_path / "contacts.sqlite3")
    repository.replace(
        (
            spot("KI5VNB", "US-1234"),
            spot("W8ABC", "US-5678"),
        ),
        SUCCESS_AT,
    )

    replacement = (spot("N8XYZ", "US-9999"),)
    repository.replace(replacement, SUCCESS_AT)

    loaded = repository.load()

    assert loaded is not None
    assert loaded.spots == replacement


def test_empty_successful_snapshot_is_cached(tmp_path) -> None:
    repository = PotaSpotCacheRepository(tmp_path / "contacts.sqlite3")

    repository.replace((), SUCCESS_AT)

    loaded = repository.load()

    assert loaded is not None
    assert loaded.spots == ()
    assert loaded.last_success_at == SUCCESS_AT


def test_naive_success_timestamp_is_rejected(tmp_path) -> None:
    repository = PotaSpotCacheRepository(tmp_path / "contacts.sqlite3")

    with pytest.raises(
        ValueError,
        match="must be timezone-aware",
    ):
        repository.replace(
            (),
            datetime(2026, 7, 27, 3, 0),  # noqa: DTZ001
        )


def test_invalid_cached_row_raises_storage_error(tmp_path) -> None:
    database_path = tmp_path / "contacts.sqlite3"
    repository = PotaSpotCacheRepository(database_path)
    repository.replace((spot(),), SUCCESS_AT)

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            UPDATE pota_spot_cache
            SET spotted_at = 'not-a-timestamp'
            """
        )
        connection.commit()

    with pytest.raises(
        StorageError,
        match="contains invalid data",
    ):
        repository.load()
