"""Tests for pure Maidenhead locator calculation."""

import pytest

from rolling_thunder.maidenhead import maidenhead_grid, maidenhead_grid_center


def test_calculates_six_character_grid() -> None:
    assert maidenhead_grid(39.5309, -84.0866) == "EM79wm"


def test_calculates_origin_grid() -> None:
    assert maidenhead_grid(0.0, 0.0) == "JJ00aa"


def test_accepts_southwest_coordinate_bounds() -> None:
    assert maidenhead_grid(-90.0, -180.0) == "AA00aa"


def test_accepts_northeast_coordinate_bounds() -> None:
    assert maidenhead_grid(90.0, 180.0) == "RR99xx"


@pytest.mark.parametrize(
    ("latitude", "longitude", "message"),
    [
        (-90.1, 0.0, "latitude"),
        (90.1, 0.0, "latitude"),
        (0.0, -180.1, "longitude"),
        (0.0, 180.1, "longitude"),
    ],
)
def test_rejects_coordinates_outside_legal_bounds(
    latitude: float,
    longitude: float,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        maidenhead_grid(latitude, longitude)



def test_grid_center_round_trips_inside_same_locator() -> None:
    latitude, longitude = maidenhead_grid_center("EM79xm")

    assert maidenhead_grid(latitude, longitude) == "EM79xm"


def test_four_character_grid_center_is_supported() -> None:
    latitude, longitude = maidenhead_grid_center("EM79")

    assert maidenhead_grid(latitude, longitude).startswith("EM79")
