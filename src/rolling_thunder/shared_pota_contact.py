"""Pure compatibility adapter from shared POTA records to contact metadata input."""

from __future__ import annotations

from rolling_thunder.pota_spots import ParkReference, PotaSpot
from rolling_thunder.spot_domain import SpotProvider, SpotRecord


def shared_pota_spots_for_contact(
    spots: tuple[SpotRecord, ...],
) -> tuple[PotaSpot, ...]:
    """Return legacy-shaped POTA values derived only from shared cached records."""
    converted: list[PotaSpot] = []
    for spot in spots:
        if spot.provider is not SpotProvider.POTA or spot.pota is None:
            continue

        comments = next(
            (item.value for item in spot.source_metadata if item.key == "comments"),
            None,
        )
        converted.append(
            PotaSpot(
                activator=spot.callsign,
                park=ParkReference(
                    reference=spot.pota.park_reference,
                    name=spot.pota.park_name,
                    location_code=spot.pota.location_code,
                    latitude=spot.pota.latitude,
                    longitude=spot.pota.longitude,
                ),
                frequency=spot.frequency,
                mode=spot.mode,
                spotted_at=spot.spotted_at,
                spot_mode=spot.display_mode,
                comments=comments,
            )
        )
    return tuple(converted)
