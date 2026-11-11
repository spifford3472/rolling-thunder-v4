"""Forge local provider contract does not activate external networking."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from rolling_thunder.forge_meshcore_geo_adapter import ForgeCatalogLookup
from rolling_thunder.forge_meshcore_geo_catalog import (
    ForgeRoadSiteCatalog,
    ReviewedRoadSite,
)
from rolling_thunder.meshcore_geographic_relevance import GeoPoint
from rolling_thunder.meshcore_traffic_geocoding import (
    ApprovedTrafficGeocoder,
    TrafficGeocodeRequest,
)

NOW = datetime(2026, 11, 11, tzinfo=UTC)


def test_catalog_adapter_reuses_existing_provider_contract(tmp_path) -> None:
    catalog = ForgeRoadSiteCatalog(tmp_path / "evidence.db", initialize=True)
    request = TrafficGeocodeRequest("I-75", "44", "Ohio, USA")
    catalog.import_reviewed(
        (
            ReviewedRoadSite(
                "I-75",
                "44",
                "Ohio, USA",
                GeoPoint(39.56, -84.10),
                "fake-reviewed-source",
                "fake-id-1",
                NOW - timedelta(days=1),
                NOW,
                point_specific=True,
            ),
        ),
        now=NOW,
    )
    provider = ApprovedTrafficGeocoder(
        lookup=ForgeCatalogLookup(catalog, now=lambda: NOW),
        enabled=True,
        clock=lambda: 100.0,
    )
    result = provider.resolve(request, now=NOW)
    assert result is not None
    assert result.road == "I-75"
    assert not result.route_alignment_verified
    assert provider.resolve(request, now=NOW) == result
