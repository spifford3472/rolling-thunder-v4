"""Fake-only Forge geographic catalog provenance and lookup gates."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from rolling_thunder.forge_meshcore_geo_catalog import (
    ForgeRoadSiteCatalog,
    GeoCatalogError,
    ReviewedRoadSite,
)
from rolling_thunder.meshcore_geographic_relevance import GeoPoint
from rolling_thunder.meshcore_traffic_geocoding import TrafficGeocodeRequest

NOW = datetime(2026, 11, 11, tzinfo=UTC)
REQ = TrafficGeocodeRequest("I-75", "44", "Ohio, USA")


def _site(
    *,
    record_id: str = "node/123",
    latitude: float = 39.56,
    reviewed_at: datetime = NOW,
    source: str = "offline-reviewed-osm",
) -> ReviewedRoadSite:
    return ReviewedRoadSite(
        road="I-75",
        exit_or_mile="44",
        region="Ohio, USA",
        point=GeoPoint(latitude, -84.1),
        source=source,
        source_record_id=record_id,
        observed_at=NOW - timedelta(days=2),
        reviewed_at=reviewed_at,
        point_specific=True,
    )


def test_missing_catalog_fail_closed_without_creating_file(tmp_path) -> None:
    p = tmp_path / "geo.db"
    with pytest.raises(GeoCatalogError):
        ForgeRoadSiteCatalog(p)
    assert not p.exists()


def test_exact_reviewed_site_is_queryable_without_online_calls(tmp_path) -> None:
    p = tmp_path / "private" / "geo.db"
    catalog = ForgeRoadSiteCatalog(p, initialize=True)
    assert catalog.health() == {
        "schema": "meshcore/road-sites/v1",
        "records": 0,
        "ready": "catalog_valid",
    }
    assert catalog.lookup(REQ, now=NOW) is None
    assert catalog.import_reviewed((_site(),), now=NOW) == 1
    # Exact immutable replay is harmless.
    assert catalog.import_reviewed((_site(),), now=NOW) == 0
    result = ForgeRoadSiteCatalog(p).lookup(REQ, now=NOW)
    assert result is not None
    assert result.road == "I-75"
    assert result.latitude == 39.56
    assert result.point_specific
    assert not result.route_alignment_verified
    assert result.direction_verified is None


def test_conflicting_source_id_and_multiple_sources_fail_closed(tmp_path) -> None:
    catalog = ForgeRoadSiteCatalog(tmp_path / "geo.db", initialize=True)
    assert catalog.import_reviewed((_site(),), now=NOW) == 1
    with pytest.raises(GeoCatalogError, match="Conflicting source identity"):
        catalog.import_reviewed((_site(latitude=39.57),), now=NOW)
    assert catalog.lookup(REQ, now=NOW) is not None
    assert (
        catalog.import_reviewed(
            (_site(source="second-reviewed-map", record_id="site-44"),), now=NOW
        )
        == 1
    )
    assert catalog.lookup(REQ, now=NOW) is None


def test_stale_and_future_reviews_rejected(tmp_path) -> None:
    catalog = ForgeRoadSiteCatalog(tmp_path / "geo.db", initialize=True)
    with pytest.raises(GeoCatalogError):
        catalog.import_reviewed((_site(reviewed_at=NOW - timedelta(days=8)),), now=NOW)
    with pytest.raises(GeoCatalogError):
        catalog.import_reviewed((_site(reviewed_at=NOW + timedelta(seconds=1)),), now=NOW)
    assert catalog.import_reviewed((_site(),), now=NOW) == 1
    assert catalog.lookup(REQ, now=NOW + timedelta(days=8)) is None


def test_exact_region_and_landmark_required(tmp_path) -> None:
    catalog = ForgeRoadSiteCatalog(tmp_path / "geo.db", initialize=True)
    catalog.import_reviewed((_site(),), now=NOW)
    assert catalog.lookup(TrafficGeocodeRequest("I-75", "45", "Ohio, USA"), now=NOW) is None
    assert catalog.lookup(TrafficGeocodeRequest("I-75", "44", "Kentucky, USA"), now=NOW) is None


def test_rejects_generic_roads_and_claimed_route_alignment() -> None:
    with pytest.raises(GeoCatalogError):
        ReviewedRoadSite(
            "I-75",
            "44",
            "Ohio, USA",
            GeoPoint(39, -84),
            "source",
            "id",
            NOW,
            NOW,
            point_specific=False,
        )
    with pytest.raises(GeoCatalogError):
        ReviewedRoadSite(
            "I-75",
            "44",
            "Ohio, USA",
            GeoPoint(39, -84),
            "source",
            "id",
            NOW,
            NOW,
            point_specific=True,
            route_alignment_verified=True,
        )


def test_database_permissions_and_schema_rejected(tmp_path) -> None:
    path = tmp_path / "geo.db"
    catalog = ForgeRoadSiteCatalog(path, initialize=True)
    assert catalog.health()["records"] == 0
    path.chmod(0o644)
    with pytest.raises(GeoCatalogError):
        catalog.lookup(REQ, now=NOW)
    path.chmod(0o600)
    with sqlite3.connect(path) as con:
        con.execute("DELETE FROM catalog_schema")
    with pytest.raises(GeoCatalogError):
        ForgeRoadSiteCatalog(path)


def test_failed_batch_rolls_back_atomic_import(tmp_path) -> None:
    catalog = ForgeRoadSiteCatalog(tmp_path / "geo.db", initialize=True)
    with pytest.raises(GeoCatalogError):
        catalog.import_reviewed((_site(), _site(latitude=39.59)), now=NOW)
    assert catalog.health()["records"] == 0
