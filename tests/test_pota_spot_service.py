"""Tests for the POTA spot refresh application service."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from rolling_thunder.domain import Frequency, RadioMode
from rolling_thunder.pota_spot_service import PotaSpotService, PotaSpotServiceState
from rolling_thunder.pota_spot_source import (
    MockPotaSpotSource,
    PotaSpotFetchResult,
    PotaSpotSourceAvailability,
    PotaSpotSourceConnectionError,
)
from rolling_thunder.pota_spots import AmateurBand, ParkReference, PotaSpot
from rolling_thunder.storage import StorageError

_ATTEMPT_1 = datetime(2026, 7, 26, 18, 0, tzinfo=UTC)
_ATTEMPT_2 = datetime(2026, 7, 26, 18, 5, tzinfo=UTC)


def _spot(callsign: str, frequency_hz: int, mode: RadioMode) -> PotaSpot:
    return PotaSpot(
        activator=callsign,
        park=ParkReference(reference="US-1234"),
        frequency=Frequency(hz=frequency_hz),
        mode=mode,
        spotted_at=_ATTEMPT_1,
    )


def _result(*spots: PotaSpot) -> PotaSpotFetchResult:
    return PotaSpotFetchResult(
        availability=PotaSpotSourceAvailability.AVAILABLE,
        spots=spots,
        fetched_at=_ATTEMPT_1,
    )


def test_service_starts_unknown_without_fetching() -> None:
    source = MockPotaSpotSource(_result())
    service = PotaSpotService(source, now=lambda: _ATTEMPT_1)

    state = service.get_state()

    assert state.availability is PotaSpotSourceAvailability.UNKNOWN
    assert state.spots == ()
    assert state.last_attempt_at is None
    assert source.fetch_count == 0


def test_successful_refresh_replaces_snapshot() -> None:
    spot = _spot("KI5VNB", 14_250_000, RadioMode.USB)
    source = MockPotaSpotSource(_result(spot))
    service = PotaSpotService(source, now=lambda: _ATTEMPT_2)

    state = service.refresh()

    assert state.availability is PotaSpotSourceAvailability.AVAILABLE
    assert state.spots == (spot,)
    assert state.last_attempt_at == _ATTEMPT_2
    assert state.last_success_at == _ATTEMPT_1
    assert state.last_error is None
    assert state.is_stale is False
    assert source.fetch_count == 1


def test_failed_refresh_retains_last_successful_snapshot() -> None:
    spot = _spot("KI5VNB", 14_250_000, RadioMode.USB)
    source = MockPotaSpotSource(_result(spot))
    attempts = iter((_ATTEMPT_1, _ATTEMPT_2))
    service = PotaSpotService(source, now=lambda: next(attempts))

    successful = service.refresh()
    source.set_error(PotaSpotSourceConnectionError("network unavailable"))
    failed = service.refresh()

    assert successful.spots == (spot,)
    assert failed.availability is PotaSpotSourceAvailability.UNAVAILABLE
    assert failed.spots == (spot,)
    assert failed.last_attempt_at == _ATTEMPT_2
    assert failed.last_success_at == _ATTEMPT_1
    assert failed.last_error == "network unavailable"
    assert failed.is_stale is True


def test_failed_initial_refresh_has_no_stale_spots() -> None:
    source = MockPotaSpotSource(
        _result(),
        error=PotaSpotSourceConnectionError("offline"),
    )
    service = PotaSpotService(source, now=lambda: _ATTEMPT_1)

    state = service.refresh()

    assert state.availability is PotaSpotSourceAvailability.UNAVAILABLE
    assert state.spots == ()
    assert state.last_success_at is None
    assert state.is_stale is False


def test_unavailable_result_is_converted_to_service_failure() -> None:
    unavailable = PotaSpotFetchResult(
        availability=PotaSpotSourceAvailability.UNAVAILABLE,
        fetched_at=_ATTEMPT_1,
        last_error="maintenance",
    )
    service = PotaSpotService(
        MockPotaSpotSource(unavailable),
        now=lambda: _ATTEMPT_2,
    )

    state = service.refresh()

    assert state.availability is PotaSpotSourceAvailability.UNAVAILABLE
    assert state.last_error == "maintenance"
    assert state.last_attempt_at == _ATTEMPT_2


def test_filtered_spots_use_retained_snapshot_without_fetching() -> None:
    usb = _spot("KI5VNB", 14_250_000, RadioMode.USB)
    data = _spot("W8O", 14_074_000, RadioMode.DATA)
    lsb = _spot("NC4XL", 7_200_000, RadioMode.LSB)
    source = MockPotaSpotSource(_result(usb, data, lsb))
    service = PotaSpotService(source, now=lambda: _ATTEMPT_1)
    service.refresh()

    filtered = service.filtered_spots(
        band=AmateurBand.BAND_20M,
        mode=RadioMode.USB,
    )

    assert filtered == (usb,)
    assert source.fetch_count == 1


def test_state_rejects_stale_spots_without_success_timestamp() -> None:
    spot = _spot("KI5VNB", 14_250_000, RadioMode.USB)

    with pytest.raises(ValidationError, match="stale POTA spots require"):
        PotaSpotServiceState(
            availability=PotaSpotSourceAvailability.UNAVAILABLE,
            spots=(spot,),
            last_attempt_at=_ATTEMPT_2,
            last_error="offline",
        )


def test_service_rejects_naive_clock() -> None:
    source = MockPotaSpotSource(_result())
    service = PotaSpotService(
        source,
        now=lambda: datetime(2026, 7, 26, 18, 0),  # noqa: DTZ001
    )

    with pytest.raises(ValueError, match="aware datetime"):
        service.refresh()



class FakeCacheSnapshot:
    def __init__(
        self,
        spots: tuple[PotaSpot, ...],
        last_success_at: datetime,
    ) -> None:
        self.spots = spots
        self.last_success_at = last_success_at


class FakeCache:
    def __init__(self) -> None:
        self.snapshot: FakeCacheSnapshot | None = None
        self.saved: tuple[tuple[PotaSpot, ...], datetime] | None = None
        self.load_error: StorageError | None = None
        self.replace_error: StorageError | None = None

    def load(self) -> FakeCacheSnapshot | None:
        if self.load_error is not None:
            raise self.load_error
        return self.snapshot

    def replace(
        self,
        spots: tuple[PotaSpot, ...],
        last_success_at: datetime,
    ) -> None:
        if self.replace_error is not None:
            raise self.replace_error
        self.saved = (spots, last_success_at)


def test_service_starts_with_cached_snapshot_as_stale() -> None:
    cache = FakeCache()
    cached_spot = _spot("KI5VNB", 14_250_000, RadioMode.USB)
    cache.snapshot = FakeCacheSnapshot(
        (cached_spot,),
        _ATTEMPT_1,
    )

    service = PotaSpotService(
        MockPotaSpotSource(
            PotaSpotFetchResult(
                availability=PotaSpotSourceAvailability.UNAVAILABLE,
                fetched_at=_ATTEMPT_1,
                last_error="offline",
            )
        ),
        cache=cache,
        now=lambda: _ATTEMPT_2,
    )

    state = service.get_state()

    assert state.availability is PotaSpotSourceAvailability.UNAVAILABLE
    assert state.spots == (cached_spot,)
    assert state.last_success_at == _ATTEMPT_1
    assert state.is_stale is True


def test_service_ignores_cache_load_failure() -> None:
    cache = FakeCache()
    cache.load_error = StorageError("cache unavailable")

    service = PotaSpotService(
        MockPotaSpotSource(
            PotaSpotFetchResult(
                availability=PotaSpotSourceAvailability.UNAVAILABLE,
                fetched_at=_ATTEMPT_1,
                last_error="offline",
            )
        ),
        cache=cache,
        now=lambda: _ATTEMPT_2,
    )

    assert service.get_state().availability is PotaSpotSourceAvailability.UNKNOWN


def test_successful_refresh_replaces_cache() -> None:
    cache = FakeCache()
    expected = (_spot("KI5VNB", 14_250_000, RadioMode.USB),)

    service = PotaSpotService(
        MockPotaSpotSource(
            PotaSpotFetchResult(
                availability=PotaSpotSourceAvailability.AVAILABLE,
                spots=expected,
                fetched_at=_ATTEMPT_1,
            )
        ),
        cache=cache,
        now=lambda: _ATTEMPT_2,
    )

    service.refresh()

    assert cache.saved == (expected, _ATTEMPT_1)


def test_cache_write_failure_does_not_fail_live_refresh() -> None:
    cache = FakeCache()
    cache.replace_error = StorageError("cache unavailable")
    expected = (_spot("KI5VNB", 14_250_000, RadioMode.USB),)

    service = PotaSpotService(
        MockPotaSpotSource(
            PotaSpotFetchResult(
                availability=PotaSpotSourceAvailability.AVAILABLE,
                spots=expected,
                fetched_at=_ATTEMPT_1,
            )
        ),
        cache=cache,
        now=lambda: _ATTEMPT_2,
    )

    state = service.refresh()

    assert state.availability is PotaSpotSourceAvailability.AVAILABLE
    assert state.spots == expected
