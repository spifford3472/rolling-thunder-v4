"""Tests for the typed POTA spot source boundary and deterministic mock."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from rolling_thunder.domain import Frequency, RadioMode
from rolling_thunder.pota_spot_source import (
    MockPotaSpotSource,
    PotaSpotFetchResult,
    PotaSpotSource,
    PotaSpotSourceAvailability,
    PotaSpotSourceConnectionError,
)
from rolling_thunder.pota_spots import ParkReference, PotaSpot

_FIXED_TIME = datetime(2026, 7, 26, 18, 0, tzinfo=UTC)


def _spot() -> PotaSpot:
    return PotaSpot(
        activator="KI5VNB/P",
        park=ParkReference(reference="US-1234"),
        frequency=Frequency(hz=14_250_000),
        mode=RadioMode.USB,
        spotted_at=_FIXED_TIME,
    )


def _available_result() -> PotaSpotFetchResult:
    return PotaSpotFetchResult(
        availability=PotaSpotSourceAvailability.AVAILABLE,
        spots=(_spot(),),
        fetched_at=_FIXED_TIME,
    )


def test_fetch_result_normalizes_operator_facing_values() -> None:
    result = PotaSpotFetchResult(
        availability=" AVAILABLE ",
        spots=[_spot()],
        fetched_at=_FIXED_TIME,
        last_error="   ",
    )

    assert result.availability is PotaSpotSourceAvailability.AVAILABLE
    assert result.spots == (_spot(),)
    assert result.fetched_at == _FIXED_TIME
    assert result.last_error is None


def test_unavailable_result_requires_error_and_rejects_spots() -> None:
    with pytest.raises(ValidationError, match="requires last_error"):
        PotaSpotFetchResult(
            availability=PotaSpotSourceAvailability.UNAVAILABLE,
            fetched_at=_FIXED_TIME,
        )

    with pytest.raises(ValidationError, match="cannot contain spots"):
        PotaSpotFetchResult(
            availability=PotaSpotSourceAvailability.UNAVAILABLE,
            spots=(_spot(),),
            fetched_at=_FIXED_TIME,
            last_error="offline",
        )


def test_available_result_rejects_error_text() -> None:
    with pytest.raises(ValidationError, match="cannot contain last_error"):
        PotaSpotFetchResult(
            availability=PotaSpotSourceAvailability.AVAILABLE,
            fetched_at=_FIXED_TIME,
            last_error="unexpected",
        )


def test_naive_fetch_timestamp_is_rejected() -> None:
    with pytest.raises(ValidationError, match="timezone information"):
        PotaSpotFetchResult(
            availability=PotaSpotSourceAvailability.UNKNOWN,
            fetched_at=datetime(2026, 7, 26, 18, 0),  # noqa: DTZ001
        )


def test_mock_source_returns_configured_result_and_counts_fetches() -> None:
    result = _available_result()
    source = MockPotaSpotSource(result)

    typed_source: PotaSpotSource = source

    assert typed_source.fetch_spots() is result
    assert source.fetch_count == 1


def test_mock_source_can_switch_from_error_to_result() -> None:
    source = MockPotaSpotSource(
        _available_result(),
        error=PotaSpotSourceConnectionError("offline"),
    )

    with pytest.raises(PotaSpotSourceConnectionError, match="offline"):
        source.fetch_spots()

    replacement = PotaSpotFetchResult(
        availability=PotaSpotSourceAvailability.AVAILABLE,
        fetched_at=_FIXED_TIME,
    )
    source.set_result(replacement)

    assert source.fetch_spots() is replacement
    assert source.fetch_count == 2


def test_mock_source_can_be_reconfigured_to_raise() -> None:
    source = MockPotaSpotSource(_available_result())
    source.set_error(PotaSpotSourceConnectionError("link down"))

    with pytest.raises(PotaSpotSourceConnectionError, match="link down"):
        source.fetch_spots()

    assert source.fetch_count == 1
