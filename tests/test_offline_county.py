"""Pure offline resolver acceptance; geometry is synthetic, not authoritative county data."""

import math

import pytest

from rolling_thunder.offline_county import CountyPolygon, OfflineCountyResolver


def square(x: float, y: float, width: float = 1.0):
    return ((x, y), (x + width, y), (x + width, y + width),
            (x, y + width), (x, y))


def test_unique_county_and_unknown() -> None:
    resolver = OfflineCountyResolver((
        CountyPolygon("OH", "WARREN", square(-85, 39)),
        CountyPolygon("OH", "GREENE", square(-84, 39)),
    ))
    assert resolver.resolve(39.5, -84.5) == ("OH", "WARREN")
    assert resolver.resolve(39.5, -83.5) == ("OH", "GREENE")
    assert resolver.resolve(40.5, -84.5) is None


def test_shared_boundary_and_overlapping_polygons_fail_closed() -> None:
    resolver = OfflineCountyResolver((
        CountyPolygon("OH", "WARREN", square(-85, 39)),
        CountyPolygon("OH", "GREENE", square(-84, 39)),
    ))
    assert resolver.resolve(39.5, -84) is None
    assert resolver.resolve(39.5, -84.00005) is None
    assert OfflineCountyResolver((
        CountyPolygon("OH", "WARREN", square(-85, 39)),
        CountyPolygon("OH", "OTHER", square(-85, 39)),
    )).resolve(39.5, -84.5) is None


def test_holes_and_multiple_components() -> None:
    resolver = OfflineCountyResolver((
        CountyPolygon("OH", "A", square(-85, 39, 2), (square(-84.5, 39.5),)),
        CountyPolygon("OH", "A", square(-82, 39)),
    ))
    assert resolver.resolve(39.2, -84.8) == ("OH", "A")
    assert resolver.resolve(39.7, -84.3) is None
    assert resolver.resolve(39.5, -81.5) == ("OH", "A")


@pytest.mark.parametrize("lat,lon", [
    (None, -84.0), (39.0, None), (math.nan, -84), (39, math.inf),
    (91, -84), (39, -181),
])
def test_invalid_position_unknown(lat, lon) -> None:
    resolver = OfflineCountyResolver((CountyPolygon("OH", "A", square(-85, 39)),))
    assert resolver.resolve(lat, lon) is None


def test_reject_malformed_geometry_and_boundary_buffer() -> None:
    with pytest.raises(ValueError):
        CountyPolygon("OH", "A", ((0, 0), (1, 0), (1, 1)))
    with pytest.raises(ValueError):
        OfflineCountyResolver((), boundary_degrees=0)
