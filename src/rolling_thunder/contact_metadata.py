"""Pure commit-time contact metadata resolution."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from rolling_thunder.domain import (
    ContactEnrichmentState,
    ContactGridSource,
    GPSFixState,
    RadioMode,
)
from rolling_thunder.gps import GPSConnectionState, GPSState
from rolling_thunder.maidenhead import maidenhead_grid
from rolling_thunder.pota_spots import PotaSpot
from rolling_thunder.value_types import MaidenheadGrid, PotaReference

POTA_FREQUENCY_TOLERANCE_HZ = 250
DEFAULT_GPS_MAXIMUM_AGE = timedelta(seconds=10)
_PHONE_MODES = frozenset({RadioMode.LSB, RadioMode.USB})


@dataclass(frozen=True, slots=True)
class ContactMetadata:
    """Optional metadata captured for one committed contact."""

    grid: MaidenheadGrid | None = None
    my_grid: MaidenheadGrid | None = None
    my_latitude: float | None = None
    my_longitude: float | None = None
    pota_reference: PotaReference | None = None
    grid_source: ContactGridSource | None = None
    enrichment_state: ContactEnrichmentState = ContactEnrichmentState.READY
    notes: str | None = None


def resolve_contact_metadata(
    *,
    callsign: str,
    frequency_hz: int,
    mode: RadioMode,
    reference_time: datetime,
    gps_state: GPSState | None = None,
    pota_context_active: bool = False,
    pota_spots: tuple[PotaSpot, ...] = (),
    qrz_fallback_available: bool = False,
    gps_maximum_age: timedelta = DEFAULT_GPS_MAXIMUM_AGE,
    frequency_tolerance_hz: int = POTA_FREQUENCY_TOLERANCE_HZ,
) -> ContactMetadata:
    """Resolve local GPS and unique POTA metadata without performing I/O."""
    if reference_time.tzinfo is None or reference_time.utcoffset() is None:
        raise ValueError("Contact metadata reference time must be timezone-aware.")
    if gps_maximum_age < timedelta(0):
        raise ValueError("GPS maximum age must not be negative.")
    if frequency_tolerance_hz < 0:
        raise ValueError("POTA frequency tolerance must not be negative.")

    my_grid = _current_my_grid(
        gps_state,
        reference_time=reference_time,
        maximum_age=gps_maximum_age,
    )

    position = gps_state.position if my_grid is not None and gps_state is not None else None
    latitude = position.latitude if position is not None else None
    longitude = position.longitude if position is not None else None

    if not pota_context_active:
        return ContactMetadata(
            my_grid=my_grid,
            my_latitude=latitude,
            my_longitude=longitude,
            enrichment_state=_enrichment_state(
                grid=None,
                qrz_fallback_available=qrz_fallback_available,
            ),
        )

    normalized_callsign = callsign.strip().upper()
    matching_parks: dict[str, PotaSpot] = {}

    for spot in pota_spots:
        if str(spot.activator) != normalized_callsign:
            continue
        if abs(spot.frequency.hz - frequency_hz) > frequency_tolerance_hz:
            continue
        if not _modes_compatible(mode, spot.mode):
            continue
        matching_parks.setdefault(spot.park.reference, spot)

    if len(matching_parks) != 1:
        return ContactMetadata(
            my_grid=my_grid,
            my_latitude=latitude,
            my_longitude=longitude,
            enrichment_state=_enrichment_state(
                grid=None,
                qrz_fallback_available=qrz_fallback_available,
            ),
        )

    spot = next(iter(matching_parks.values()))
    park_reference = spot.park.reference
    grid: MaidenheadGrid | None = None
    grid_source: ContactGridSource | None = None

    if spot.park.latitude is not None and spot.park.longitude is not None:
        grid = maidenhead_grid(
            spot.park.latitude,
            spot.park.longitude,
        )
        grid_source = ContactGridSource.POTA_PARK

    return ContactMetadata(
        grid=grid,
        my_grid=my_grid,
        my_latitude=latitude,
        my_longitude=longitude,
        pota_reference=park_reference,
        grid_source=grid_source,
        enrichment_state=_enrichment_state(
            grid=grid,
            qrz_fallback_available=qrz_fallback_available,
        ),
        notes=f"POTA {park_reference}",
    )


def _enrichment_state(
    *,
    grid: MaidenheadGrid | None,
    qrz_fallback_available: bool,
) -> ContactEnrichmentState:
    if grid is None and qrz_fallback_available:
        return ContactEnrichmentState.PENDING_QRZ
    return ContactEnrichmentState.READY


def _current_my_grid(
    gps_state: GPSState | None,
    *,
    reference_time: datetime,
    maximum_age: timedelta,
) -> MaidenheadGrid | None:
    if (
        gps_state is None
        or gps_state.connection_state is not GPSConnectionState.CONNECTED
        or gps_state.position is None
        or gps_state.position.fix_state is GPSFixState.NO_FIX
        or gps_state.position.latitude is None
        or gps_state.position.longitude is None
    ):
        return None

    age = max(
        timedelta(0),
        reference_time - gps_state.position.updated_at,
    )
    if age > maximum_age:
        return None

    return maidenhead_grid(
        gps_state.position.latitude,
        gps_state.position.longitude,
    )


def _modes_compatible(left: RadioMode, right: RadioMode) -> bool:
    if left is right:
        return True
    return left in _PHONE_MODES and right in _PHONE_MODES
