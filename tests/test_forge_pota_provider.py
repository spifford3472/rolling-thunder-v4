"""Tests for public-POTA normalization into the shared Forge domain."""

from datetime import UTC, datetime, timedelta

import pytest

from rolling_thunder.domain import Frequency, RadioMode
from rolling_thunder.forge_pota_provider import (
    ForgePotaSpotProvider,
    map_pota_spot_to_shared,
)
from rolling_thunder.forge_spot_provider import (
    ForgeSpotProviderConnectionError,
    ForgeSpotProviderResponseError,
)
from rolling_thunder.pota_spot_source import (
    MockPotaSpotSource,
    PotaSpotFetchResult,
    PotaSpotSourceAvailability,
    PotaSpotSourceConnectionError,
    PotaSpotSourceResponseError,
)
from rolling_thunder.pota_spots import ParkReference, PotaSpot
from rolling_thunder.spot_domain import PotaSpotIdentity, SpotProvider

BASE_TIME = datetime(2026, 8, 5, 20, 0, tzinfo=UTC)


def pota_spot(
    callsign: str,
    reference: str,
    frequency_hz: int,
    *,
    spotted_at: datetime = BASE_TIME,
    comments: str | None = None,
    latitude: float | None = 39.75,
    longitude: float | None = -84.2,
) -> PotaSpot:
    return PotaSpot(
        activator=callsign,
        park=ParkReference(
            reference=reference,
            name="Test State Park",
            location_code="US-OH",
            latitude=latitude,
            longitude=longitude,
        ),
        frequency=Frequency(hz=frequency_hz),
        mode=RadioMode.USB,
        spot_mode="SSB",
        spotted_at=spotted_at,
        comments=comments,
    )


def available_result(*spots: PotaSpot) -> PotaSpotFetchResult:
    return PotaSpotFetchResult(
        availability=PotaSpotSourceAvailability.AVAILABLE,
        spots=spots,
        fetched_at=BASE_TIME + timedelta(seconds=10),
    )


def test_map_pota_spot_preserves_shared_action_and_park_fields() -> None:
    source_spot = pota_spot(
        "ki5vnb",
        "us-1234",
        14_250_000,
        comments="  strong signal  ",
    )

    shared = map_pota_spot_to_shared(source_spot)

    assert shared.provider is SpotProvider.POTA
    assert isinstance(shared.identity, PotaSpotIdentity)
    assert shared.identity.park_reference == "US-1234"
    assert shared.callsign == "KI5VNB"
    assert shared.operator_name is None
    assert shared.grid is None
    assert shared.frequency.hz == 14_250_000
    assert shared.mode is RadioMode.USB
    assert shared.display_mode == "SSB"
    assert shared.spotted_at == BASE_TIME
    assert shared.source_metadata[0].key == "comments"
    assert shared.source_metadata[0].value == "strong signal"
    assert shared.pota is not None
    assert shared.pota.park_reference == "US-1234"
    assert shared.pota.park_name == "Test State Park"
    assert shared.pota.location_code == "US-OH"
    assert shared.pota.latitude == 39.75
    assert shared.pota.longitude == -84.2


def test_map_pota_spot_drops_incomplete_optional_coordinate_pair() -> None:
    shared = map_pota_spot_to_shared(
        pota_spot(
            "KI5VNB",
            "US-1234",
            14_250_000,
            latitude=39.75,
            longitude=None,
        )
    )

    assert shared.pota is not None
    assert shared.pota.latitude is None
    assert shared.pota.longitude is None


def test_provider_returns_canonical_complete_slice() -> None:
    older = pota_spot("KI5VNB", "US-1234", 14_250_000)
    newer = pota_spot(
        "W8NEW",
        "US-1234",
        14_250_000,
        spotted_at=BASE_TIME + timedelta(seconds=2),
    )
    lower = pota_spot("K1LOW", "US-1000", 7_200_000)
    source = MockPotaSpotSource(available_result(newer, older, lower))
    provider = ForgePotaSpotProvider(source)

    provider_slice = provider.fetch_slice()

    assert provider.provider is SpotProvider.POTA
    assert provider_slice.provider is SpotProvider.POTA
    assert provider_slice.fetched_at == BASE_TIME + timedelta(seconds=10)
    assert [str(spot.callsign) for spot in provider_slice.spots] == ["K1LOW", "W8NEW"]
    assert source.fetch_count == 1


def test_successful_empty_provider_slice_is_valid() -> None:
    provider = ForgePotaSpotProvider(MockPotaSpotSource(available_result()))

    provider_slice = provider.fetch_slice()

    assert provider_slice.spots == ()


def test_source_connection_error_maps_to_forge_connection_error() -> None:
    source = MockPotaSpotSource(
        available_result(),
        error=PotaSpotSourceConnectionError("network down"),
    )
    provider = ForgePotaSpotProvider(source)

    with pytest.raises(ForgeSpotProviderConnectionError, match="network down"):
        provider.fetch_slice()


def test_source_response_error_maps_to_forge_response_error() -> None:
    source = MockPotaSpotSource(
        available_result(),
        error=PotaSpotSourceResponseError("bad payload"),
    )
    provider = ForgePotaSpotProvider(source)

    with pytest.raises(ForgeSpotProviderResponseError, match="bad payload"):
        provider.fetch_slice()


def test_unavailable_result_maps_to_forge_connection_error() -> None:
    source = MockPotaSpotSource(
        PotaSpotFetchResult(
            availability=PotaSpotSourceAvailability.UNAVAILABLE,
            fetched_at=BASE_TIME,
            last_error="provider maintenance",
        )
    )
    provider = ForgePotaSpotProvider(source)

    with pytest.raises(
        ForgeSpotProviderConnectionError,
        match="provider maintenance",
    ):
        provider.fetch_slice()


def test_unknown_result_maps_to_forge_response_error() -> None:
    source = MockPotaSpotSource(
        PotaSpotFetchResult(
            availability=PotaSpotSourceAvailability.UNKNOWN,
            fetched_at=BASE_TIME,
        )
    )
    provider = ForgePotaSpotProvider(source)

    with pytest.raises(ForgeSpotProviderResponseError, match="unknown"):
        provider.fetch_slice()
