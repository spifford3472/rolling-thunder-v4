"""Tests for contact metadata compatibility from shared POTA records."""

from datetime import UTC, datetime

from rolling_thunder.domain import Frequency, RadioMode
from rolling_thunder.shared_pota_contact import shared_pota_spots_for_contact
from rolling_thunder.spot_domain import (
    DxSpotIdentity,
    PotaSpotIdentity,
    PotaSpotMetadata,
    SpotRecord,
    SpotSourceMetadataItem,
)

SPOTTED = datetime(2026, 8, 8, 1, 0, tzinfo=UTC)


def test_shared_pota_record_converts_without_network_or_repository_dependency() -> None:
    frequency = Frequency(hz=14_250_000)
    shared = SpotRecord(
        identity=PotaSpotIdentity(park_reference="US-1234", frequency=frequency),
        callsign="K1POTA",
        frequency=frequency,
        mode=RadioMode.USB,
        display_mode="SSB",
        spotted_at=SPOTTED,
        source_metadata=(SpotSourceMetadataItem(key="comments", value="portable"),),
        pota=PotaSpotMetadata(
            park_reference="US-1234",
            park_name="Example Park",
            location_code="US-OH",
            latitude=39.7,
            longitude=-84.1,
        ),
    )

    converted = shared_pota_spots_for_contact((shared,))

    assert len(converted) == 1
    spot = converted[0]
    assert str(spot.activator) == "K1POTA"
    assert spot.park.reference == "US-1234"
    assert spot.park.name == "Example Park"
    assert spot.park.location_code == "US-OH"
    assert spot.park.latitude == 39.7
    assert spot.frequency == frequency
    assert spot.mode is RadioMode.USB
    assert spot.spot_mode == "SSB"
    assert spot.comments == "portable"


def test_dx_records_are_not_exposed_as_pota_contact_candidates() -> None:
    frequency = Frequency(hz=14_020_000)
    dx = SpotRecord(
        identity=DxSpotIdentity(callsign="K1DX", frequency=frequency),
        callsign="K1DX",
        frequency=frequency,
        mode=RadioMode.CW,
        display_mode="CW",
        spotted_at=SPOTTED,
    )

    assert shared_pota_spots_for_contact((dx,)) == ()
