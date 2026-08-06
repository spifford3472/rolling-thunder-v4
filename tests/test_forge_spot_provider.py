"""Tests for complete provider-neutral Forge spot slices."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from rolling_thunder.domain import Frequency, RadioMode
from rolling_thunder.forge_spot_provider import (
    ForgeProviderSlice,
    ForgeSpotProviderConnectionError,
    MockForgeSpotProvider,
)
from rolling_thunder.spot_domain import (
    DxSpotIdentity,
    PotaSpotIdentity,
    PotaSpotMetadata,
    SpotProvider,
    SpotRecord,
)

BASE_TIME = datetime(2026, 8, 5, 20, 0, tzinfo=UTC)


def pota_spot(
    callsign: str,
    reference: str,
    frequency_hz: int,
    *,
    spotted_at: datetime = BASE_TIME,
) -> SpotRecord:
    frequency = Frequency(hz=frequency_hz)
    return SpotRecord(
        identity=PotaSpotIdentity(
            park_reference=reference,
            frequency=frequency,
        ),
        callsign=callsign,
        frequency=frequency,
        mode=RadioMode.USB,
        display_mode="SSB",
        spotted_at=spotted_at,
        pota=PotaSpotMetadata(park_reference=reference),
    )


def dx_spot(callsign: str, frequency_hz: int) -> SpotRecord:
    frequency = Frequency(hz=frequency_hz)
    return SpotRecord(
        identity=DxSpotIdentity(
            callsign=callsign,
            frequency=frequency,
        ),
        callsign=callsign,
        frequency=frequency,
        mode=RadioMode.CW,
        display_mode="CW",
        spotted_at=BASE_TIME,
    )


def test_from_spots_canonicalizes_order_and_duplicates() -> None:
    older = pota_spot("KI5VNB", "US-1234", 14_250_000)
    newer = pota_spot(
        "W8NEW",
        "US-1234",
        14_250_000,
        spotted_at=BASE_TIME + timedelta(seconds=1),
    )
    lower = pota_spot("K1LOW", "US-1000", 7_200_000)

    provider_slice = ForgeProviderSlice.from_spots(
        provider=SpotProvider.POTA,
        fetched_at=BASE_TIME + timedelta(seconds=2),
        spots=(newer, older, lower),
    )

    assert provider_slice.provider is SpotProvider.POTA
    assert provider_slice.fetched_at == BASE_TIME + timedelta(seconds=2)
    assert provider_slice.spots == (lower, newer)


def test_direct_slice_rejects_noncanonical_order() -> None:
    lower = pota_spot("K1LOW", "US-1000", 7_200_000)
    higher = pota_spot("K1HIGH", "US-2000", 14_250_000)

    with pytest.raises(ValidationError, match="canonical"):
        ForgeProviderSlice(
            provider=SpotProvider.POTA,
            fetched_at=BASE_TIME,
            spots=(higher, lower),
        )


def test_slice_rejects_records_from_another_provider() -> None:
    with pytest.raises(ValidationError, match="another provider"):
        ForgeProviderSlice.from_spots(
            provider=SpotProvider.POTA,
            fetched_at=BASE_TIME,
            spots=(dx_spot("K1ABC", 14_025_000),),
        )


def test_slice_requires_timezone_aware_fetch_time() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        ForgeProviderSlice.from_spots(
            provider=SpotProvider.POTA,
            fetched_at=datetime(2026, 8, 5, 20, 0),
            spots=(),
        )


def test_mock_provider_returns_slice_and_counts_fetches() -> None:
    provider_slice = ForgeProviderSlice.from_spots(
        provider=SpotProvider.POTA,
        fetched_at=BASE_TIME,
        spots=(pota_spot("KI5VNB", "US-1234", 14_250_000),),
    )
    provider = MockForgeSpotProvider(provider_slice)

    assert provider.provider is SpotProvider.POTA
    assert provider.fetch_slice() == provider_slice
    assert provider.fetch_slice() == provider_slice
    assert provider.fetch_count == 2


def test_mock_provider_raises_typed_error() -> None:
    provider_slice = ForgeProviderSlice.from_spots(
        provider=SpotProvider.POTA,
        fetched_at=BASE_TIME,
        spots=(),
    )
    expected = ForgeSpotProviderConnectionError("offline")
    provider = MockForgeSpotProvider(provider_slice, error=expected)

    with pytest.raises(ForgeSpotProviderConnectionError, match="offline"):
        provider.fetch_slice()

    assert provider.fetch_count == 1


def test_mock_provider_rejects_provider_family_change() -> None:
    pota_slice = ForgeProviderSlice.from_spots(
        provider=SpotProvider.POTA,
        fetched_at=BASE_TIME,
        spots=(),
    )
    dx_slice = ForgeProviderSlice.from_spots(
        provider=SpotProvider.DX,
        fetched_at=BASE_TIME,
        spots=(),
    )
    provider = MockForgeSpotProvider(pota_slice)

    with pytest.raises(ValueError, match="same provider"):
        provider.set_slice(dx_slice)
