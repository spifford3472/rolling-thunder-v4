"""Forge adapter that normalizes the existing public POTA source."""

from pydantic import ValidationError

from rolling_thunder.forge_spot_provider import (
    ForgeProviderSlice,
    ForgeSpotProviderConnectionError,
    ForgeSpotProviderNormalizationError,
    ForgeSpotProviderResponseError,
)
from rolling_thunder.pota_spot_source import (
    PotaSpotSource,
    PotaSpotSourceAvailability,
    PotaSpotSourceConnectionError,
    PotaSpotSourceResponseError,
)
from rolling_thunder.pota_spots import PotaSpot
from rolling_thunder.spot_domain import (
    PotaSpotIdentity,
    PotaSpotMetadata,
    SpotProvider,
    SpotRecord,
    SpotSourceMetadataItem,
)


class ForgePotaSpotProvider:
    """Convert complete public POTA snapshots into the shared spot domain."""

    def __init__(self, source: PotaSpotSource) -> None:
        self._source = source

    @property
    def provider(self) -> SpotProvider:
        """Return the POTA shared provider family."""
        return SpotProvider.POTA

    def fetch_slice(self) -> ForgeProviderSlice:
        """Fetch and normalize one complete canonical POTA provider slice."""
        try:
            result = self._source.fetch_spots()
        except PotaSpotSourceConnectionError as error:
            raise ForgeSpotProviderConnectionError(str(error)) from error
        except PotaSpotSourceResponseError as error:
            raise ForgeSpotProviderResponseError(str(error)) from error

        if result.availability is PotaSpotSourceAvailability.UNAVAILABLE:
            raise ForgeSpotProviderConnectionError(
                result.last_error or "POTA provider is unavailable."
            )
        if result.availability is not PotaSpotSourceAvailability.AVAILABLE:
            raise ForgeSpotProviderResponseError(
                "POTA provider returned an unknown availability state."
            )

        try:
            normalized = tuple(map_pota_spot_to_shared(spot) for spot in result.spots)
            return ForgeProviderSlice.from_spots(
                provider=self.provider,
                fetched_at=result.fetched_at,
                spots=normalized,
            )
        except (TypeError, ValueError, ValidationError) as error:
            raise ForgeSpotProviderNormalizationError(
                f"POTA provider records could not be normalized: {error}"
            ) from error


def map_pota_spot_to_shared(spot: PotaSpot) -> SpotRecord:
    """Map one validated POTA spot into one shared immutable record."""
    latitude, longitude = _coordinate_pair(spot)
    source_metadata = (
        (
            SpotSourceMetadataItem(
                key="comments",
                value=spot.comments,
            ),
        )
        if spot.comments is not None
        else ()
    )

    identity = PotaSpotIdentity(
        callsign=spot.activator,
        park_reference=spot.park.reference,
        frequency=spot.frequency,
    )
    return SpotRecord(
        identity=identity,
        callsign=spot.activator,
        operator_name=None,
        grid=None,
        frequency=spot.frequency,
        mode=spot.mode,
        display_mode=spot.display_mode,
        spotted_at=spot.spotted_at,
        source_metadata=source_metadata,
        pota=PotaSpotMetadata(
            park_reference=spot.park.reference,
            park_name=spot.park.name,
            location_code=spot.park.location_code,
            latitude=latitude,
            longitude=longitude,
        ),
    )


def _coordinate_pair(spot: PotaSpot) -> tuple[float | None, float | None]:
    """Preserve park coordinates only when a complete pair is available."""
    latitude = spot.park.latitude
    longitude = spot.park.longitude
    if latitude is None or longitude is None:
        return None, None
    return latitude, longitude
