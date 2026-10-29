"""Tests for pure commit-time GPS and POTA contact metadata."""

from datetime import UTC, datetime, timedelta

from rolling_thunder.contact_metadata import resolve_contact_metadata
from rolling_thunder.domain import (
    ContactEnrichmentState,
    ContactGridSource,
    Frequency,
    GPSFixState,
    GPSPosition,
    RadioMode,
)
from rolling_thunder.gps import GPSConnectionState, GPSState
from rolling_thunder.pota_spots import ParkReference, PotaSpot


def timestamp() -> datetime:
    return datetime(2026, 8, 2, 23, 30, tzinfo=UTC)


def gps_state(*, age_s: int = 0) -> GPSState:
    position = GPSPosition(
        fix_state=GPSFixState.THREE_DIMENSIONAL,
        latitude=39.5309,
        longitude=-84.0866,
        altitude_m=250.0,
        satellites=9,
        updated_at=timestamp() - timedelta(seconds=age_s),
    )
    return GPSState(
        connection_state=GPSConnectionState.CONNECTED,
        position=position,
        updated_at=position.updated_at,
    )


def spot(
    *,
    callsign: str = "K8ABC",
    park_reference: str = "US-1234",
    frequency_hz: int = 7_248_000,
    mode: RadioMode = RadioMode.LSB,
    latitude: float | None = 40.0,
    longitude: float | None = -83.0,
) -> PotaSpot:
    return PotaSpot(
        activator=callsign,
        park=ParkReference(
            reference=park_reference,
            latitude=latitude,
            longitude=longitude,
        ),
        frequency=Frequency(hz=frequency_hz),
        mode=mode,
        spotted_at=timestamp() - timedelta(minutes=2),
    )


def resolve(
    *,
    callsign: str = "K8ABC",
    frequency_hz: int = 7_248_000,
    mode: RadioMode = RadioMode.LSB,
    gps: GPSState | None = None,
    active: bool = True,
    spots: tuple[PotaSpot, ...] = (),
    qrz_available: bool = False,
):
    return resolve_contact_metadata(
        callsign=callsign,
        frequency_hz=frequency_hz,
        mode=mode,
        reference_time=timestamp(),
        gps_state=gps,
        pota_context_active=active,
        pota_spots=spots,
        qrz_fallback_available=qrz_available,
    )


def test_recent_valid_gps_populates_my_grid() -> None:
    metadata = resolve(gps=gps_state(), active=False)

    assert metadata.my_grid == "EM79wm"
    assert metadata.grid is None


def test_gps_at_120_seconds_is_still_accepted() -> None:
    metadata = resolve(gps=gps_state(age_s=120), active=False)

    assert metadata.my_grid == "EM79wm"


def test_stale_gps_does_not_populate_my_grid() -> None:
    metadata = resolve(gps=gps_state(age_s=121), active=False)

    assert metadata.my_grid is None


def test_unique_pota_match_records_park_grid_reference_and_notes() -> None:
    metadata = resolve(
        gps=gps_state(),
        spots=(spot(),),
    )

    assert metadata.my_grid == "EM79wm"
    assert metadata.grid == "EN80ma"
    assert metadata.grid_source is ContactGridSource.POTA_PARK
    assert metadata.pota_reference == "US-1234"
    assert metadata.notes is None


def test_pota_match_without_coordinates_still_records_reference() -> None:
    metadata = resolve(
        spots=(spot(latitude=None, longitude=None),),
    )

    assert metadata.grid is None
    assert metadata.grid_source is None
    assert metadata.pota_reference == "US-1234"
    assert metadata.notes is None


def test_non_pota_context_does_not_associate_a_park() -> None:
    metadata = resolve(
        active=False,
        spots=(spot(),),
    )

    assert metadata.pota_reference is None
    assert metadata.notes is None


def test_callsign_frequency_and_mode_must_all_match() -> None:
    mismatches = (
        spot(callsign="N8XYZ"),
        spot(frequency_hz=7_248_251),
        spot(mode=RadioMode.CW),
    )

    for candidate in mismatches:
        metadata = resolve(spots=(candidate,))
        assert metadata.pota_reference is None


def test_phone_modes_are_compatible() -> None:
    metadata = resolve(
        mode=RadioMode.USB,
        spots=(spot(mode=RadioMode.LSB),),
    )

    assert metadata.pota_reference == "US-1234"


def test_ambiguous_distinct_parks_do_not_guess() -> None:
    metadata = resolve(
        spots=(
            spot(park_reference="US-1234"),
            spot(park_reference="US-5678"),
        ),
    )

    assert metadata.pota_reference is None
    assert metadata.grid is None


def test_duplicate_spots_for_same_park_remain_unambiguous() -> None:
    metadata = resolve(
        spots=(
            spot(park_reference="US-1234"),
            spot(park_reference="US-1234"),
        ),
    )

    assert metadata.pota_reference == "US-1234"


def test_qrz_fallback_marks_contact_pending_without_contacted_grid() -> None:
    metadata = resolve(
        active=False,
        qrz_available=True,
    )

    assert metadata.grid is None
    assert metadata.enrichment_state is ContactEnrichmentState.PENDING_QRZ


def test_pota_grid_takes_precedence_over_qrz_fallback() -> None:
    metadata = resolve(
        spots=(spot(),),
        qrz_available=True,
    )

    assert metadata.grid == "EN80ma"
    assert metadata.grid_source is ContactGridSource.POTA_PARK
    assert metadata.enrichment_state is ContactEnrichmentState.READY


def test_pota_reference_without_coordinates_uses_qrz_fallback() -> None:
    metadata = resolve(
        spots=(spot(latitude=None, longitude=None),),
        qrz_available=True,
    )

    assert metadata.pota_reference == "US-1234"
    assert metadata.grid is None
    assert metadata.enrichment_state is ContactEnrichmentState.PENDING_QRZ
