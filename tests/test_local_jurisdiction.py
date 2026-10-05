"""Deterministic offline state/CQ/ITU jurisdiction resolution."""

import json
from pathlib import Path

import pytest

from rolling_thunder.local_jurisdiction import (
    LocalJurisdiction,
    LocalJurisdictionResolver,
    StateBoundary,
    load_state_boundaries,
)


def square(state: str, *, west: float, south: float, east: float, north: float) -> StateBoundary:
    return StateBoundary(
        state=state,
        polygons=(
            (
                (
                    (west, south),
                    (east, south),
                    (east, north),
                    (west, north),
                ),
            ),
        ),
    )


def test_resolves_interior_state_and_zones() -> None:
    resolver = LocalJurisdictionResolver(
        (
            square("OH", west=-85.0, south=38.0, east=-80.0, north=42.0),
            square("IN", west=-90.0, south=37.0, east=-85.0, north=42.0),
            square("KY", west=-90.0, south=36.0, east=-85.0, north=37.0),
        )
    )

    assert resolver.resolve(39.53, -84.09) == LocalJurisdiction(
        state="OH",
        cq_zone=4,
        itu_zone=8,
    )
    assert resolver.resolve(40.0, -86.0) == LocalJurisdiction(
        state="IN",
        cq_zone=4,
        itu_zone=8,
    )


def test_exact_state_boundary_fails_closed() -> None:
    resolver = LocalJurisdictionResolver(
        (
            square("OH", west=-85.0, south=38.0, east=-80.0, north=42.0),
            square("IN", west=-90.0, south=38.0, east=-85.0, north=42.0),
        )
    )
    assert resolver.resolve(40.0, -85.0) is None


def test_polygon_hole_is_not_assigned() -> None:
    resolver = LocalJurisdictionResolver(
        (
            StateBoundary(
                state="OH",
                polygons=(
                    (
                        ((-85.0, 38.0), (-80.0, 38.0), (-80.0, 42.0), (-85.0, 42.0)),
                        ((-83.0, 39.0), (-82.0, 39.0), (-82.0, 40.0), (-83.0, 40.0)),
                    ),
                ),
            ),
        )
    )
    assert resolver.resolve(39.5, -82.5) is None
    assert resolver.resolve(40.5, -82.5) == LocalJurisdiction("OH", 4, 8)


def test_multipolygon_is_supported() -> None:
    resolver = LocalJurisdictionResolver(
        (
            StateBoundary(
                state="HI",
                polygons=(
                    (((-160.0, 20.0), (-159.0, 20.0), (-159.0, 21.0), (-160.0, 21.0)),),
                    (((-158.0, 21.0), (-157.0, 21.0), (-157.0, 22.0), (-158.0, 22.0)),),
                ),
            ),
        )
    )
    assert resolver.resolve(20.5, -159.5) == LocalJurisdiction("HI", 31, 61)
    assert resolver.resolve(21.5, -157.5) == LocalJurisdiction("HI", 31, 61)


@pytest.mark.parametrize(
    ("state", "longitude", "zone"),
    [
        ("AZ", -111.0, 6),
        ("AZ", -109.0, 7),
        ("MT", -111.0, 6),
        ("MT", -109.0, 7),
        ("IL", -91.0, 7),
        ("IL", -89.0, 8),
        ("AK", -142.0, 1),
        ("AK", -140.0, 2),
    ],
)
def test_itu_longitude_boundaries(state: str, longitude: float, zone: int) -> None:
    resolver = LocalJurisdictionResolver(
        (square(state, west=-180.0, south=0.0, east=-60.0, north=75.0),)
    )
    result = resolver.resolve(40.0, longitude)
    assert result is not None
    assert result.itu_zone == zone


@pytest.mark.parametrize(
    ("state", "longitude"),
    [("AZ", -110.0), ("IL", -90.0), ("AK", -141.0)],
)
def test_exact_itu_meridian_fails_closed(state: str, longitude: float) -> None:
    resolver = LocalJurisdictionResolver(
        (square(state, west=-180.0, south=0.0, east=-60.0, north=75.0),)
    )
    assert resolver.resolve(40.0, longitude) is None


def test_outside_supported_state_does_not_choose_nearest() -> None:
    resolver = LocalJurisdictionResolver(
        (square("OH", west=-85.0, south=38.0, east=-80.0, north=42.0),)
    )
    assert resolver.resolve(43.0, -82.0) is None


@pytest.mark.parametrize(
    ("latitude", "longitude", "error"),
    [
        (91.0, -84.0, ValueError),
        (39.0, -181.0, ValueError),
        (float("nan"), -84.0, ValueError),
        (39.0, float("inf"), ValueError),
        (True, -84.0, TypeError),
        (39.0, False, TypeError),
    ],
)
def test_invalid_coordinates_are_rejected(
    latitude: float,
    longitude: float,
    error: type[Exception],
) -> None:
    resolver = LocalJurisdictionResolver(
        (square("OH", west=-85.0, south=38.0, east=-80.0, north=42.0),)
    )
    with pytest.raises(error):
        resolver.resolve(latitude, longitude)


def test_state_code_is_normalized_and_boundaries_are_unique() -> None:
    boundary = square(" oh ", west=-85.0, south=38.0, east=-80.0, north=42.0)
    assert boundary.state == "OH"
    with pytest.raises(ValueError, match="unique"):
        LocalJurisdictionResolver((boundary, boundary))



def test_versioned_artifact_loader_round_trips_boundaries(tmp_path: Path) -> None:
    artifact = tmp_path / "jurisdiction.json"
    artifact.write_text(
        json.dumps(
            {
                "format_version": 1,
                "source": {"dataset": "test"},
                "states": [
                    {
                        "state": "OH",
                        "polygons": [
                            [
                                [
                                    [-85.0, 38.0],
                                    [-80.0, 38.0],
                                    [-80.0, 42.0],
                                    [-85.0, 42.0],
                                    [-85.0, 38.0],
                                ]
                            ]
                        ],
                    }
                ],
            }
        )
    )

    boundaries = load_state_boundaries(artifact)
    resolver = LocalJurisdictionResolver(boundaries)

    assert resolver.resolve(39.5, -84.0) == LocalJurisdiction("OH", 4, 8)


def test_artifact_loader_rejects_unknown_format(tmp_path: Path) -> None:
    artifact = tmp_path / "jurisdiction.json"
    artifact.write_text(json.dumps({"format_version": 99, "states": []}))
    with pytest.raises(ValueError, match="unsupported"):
        load_state_boundaries(artifact)
