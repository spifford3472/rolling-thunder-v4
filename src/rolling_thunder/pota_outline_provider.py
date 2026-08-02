"""Route POTA map requests to U.S. or global administrative providers."""

from rolling_thunder.census_state_outline import CensusStateOutlineProvider
from rolling_thunder.geoboundaries_outline import GeoBoundariesOutlineProvider
from rolling_thunder.pota_enrichment import StateOutline
from rolling_thunder.pota_spots import ParkReference


class PotaOutlineProvider:
    """Use Census for U.S. subdivisions and geoBoundaries for DX parks."""

    def __init__(
        self,
        us_provider: CensusStateOutlineProvider,
        dx_provider: GeoBoundariesOutlineProvider,
    ) -> None:
        self._us_provider = us_provider
        self._dx_provider = dx_provider

    def fetch_outline(self, park: ParkReference) -> StateOutline | None:
        """Return the best available administrative outline for one park."""
        country_code = self._country_code(park)
        if country_code == "US":
            return self._us_provider.fetch_outline(park)
        return self._dx_provider.fetch_outline(park)

    @staticmethod
    def _country_code(park: ParkReference) -> str | None:
        source = park.location_code or park.reference
        prefix = source.strip().upper().split("-", 1)[0]
        return prefix if len(prefix) == 2 and prefix.isalpha() else None
