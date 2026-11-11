"""Read-only catalog adapter for the existing injected geocoding contract.

This local Forge adapter has no HTTP client and is not automatically composed
into anvilmobile's worker or any long-running service.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from rolling_thunder.forge_meshcore_geo_catalog import ForgeRoadSiteCatalog
from rolling_thunder.meshcore_traffic_geocoding import (
    TrafficGeocodeRequest,
    TrafficGeocodeResult,
)


class ForgeCatalogLookup:
    """Adapt explicit catalog query to the reusable provider callback."""

    def __init__(
        self,
        catalog: ForgeRoadSiteCatalog,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._catalog = catalog
        self._now = now

    def __call__(self, request: TrafficGeocodeRequest) -> TrafficGeocodeResult | None:
        """Look up one site without reading any network, radio or GPS source."""

        return self._catalog.lookup(request, now=self._now())
