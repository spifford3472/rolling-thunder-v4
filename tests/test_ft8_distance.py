"""Tests for Maidenhead grid-center distance used by FT8."""

import pytest

from rolling_thunder.ft8.distance import (
    format_maidenhead_distance,
    initial_ft8_power_watts,
    maidenhead_distance_km,
    maidenhead_distance_miles,
)


def test_same_grid_distance_is_zero() -> None:
    assert maidenhead_distance_km("EM79xm", "EM79xm") == pytest.approx(0.0)
    assert maidenhead_distance_miles("EM79xm", "EM79xm") == pytest.approx(0.0)


def test_distance_is_symmetric_and_uses_grid_centers() -> None:
    forward = maidenhead_distance_km("EM79xm", "FN31pr")
    reverse = maidenhead_distance_km("FN31pr", "EM79xm")

    assert forward == pytest.approx(reverse)
    assert 900 < forward < 1_200


def test_distance_formatter_uses_operator_friendly_miles() -> None:
    text = format_maidenhead_distance("EM79xm", "FN31pr")

    assert text.startswith("DISTANCE ")
    assert text.endswith(" mi")
    assert "—" not in text


def test_adaptive_initial_power_keeps_nearby_paths_low_and_extreme_paths_at_cap() -> None:
    assert initial_ft8_power_watts("EM79xm", "FN31pr") == 20
    assert initial_ft8_power_watts("EM79xm", "QF56") == 70


@pytest.mark.parametrize(
    ("distance_grid", "expected_watts"),
    [
        ("EM79xm", 20),
        (None, 20),
        ("INVALID", 20),
    ],
)
def test_adaptive_initial_power_defaults_safely(
    distance_grid: str | None,
    expected_watts: int,
) -> None:
    assert initial_ft8_power_watts("EM79xm", distance_grid) == expected_watts


@pytest.mark.parametrize(
    ("local_grid", "remote_grid"),
    [(None, "FN31pr"), ("EM79xm", None), ("INVALID", "FN31pr")],
)
def test_distance_formatter_is_explicit_when_unavailable(
    local_grid: str | None,
    remote_grid: str | None,
) -> None:
    assert format_maidenhead_distance(local_grid, remote_grid) == "DISTANCE —"
