"""Tests for reusable validated scalar types."""

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from rolling_thunder.value_types import (
    BaseCallsign,
    Callsign,
    MaidenheadGrid,
)


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("ki5vnb", "KI5VNB"),
        (" W8O ", "W8O"),
        ("ki5vnb/p", "KI5VNB/P"),
        ("w8o/m", "W8O/M"),
    ],
)
def test_callsign_normalization(raw_value: str, expected: str) -> None:
    """Station callsigns should normalize case and surrounding whitespace."""
    adapter = TypeAdapter(Callsign)

    assert adapter.validate_python(raw_value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        "INVALID",
        "KI5VNB/",
        "/KI5VNB",
        "KI5VNB/PORTABLE",
        123,
    ],
)
def test_callsign_rejects_invalid_values(value: object) -> None:
    """Station callsigns must satisfy the supported structural format."""
    adapter = TypeAdapter(Callsign)

    with pytest.raises(ValidationError):
        adapter.validate_python(value)


def test_base_callsign_rejects_operating_suffix() -> None:
    """Configured operator identity should remain a base callsign."""
    adapter = TypeAdapter(BaseCallsign)

    with pytest.raises(ValidationError):
        adapter.validate_python("KI5VNB/P")


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("em79", "EM79"),
        (" em79XM ", "EM79xm"),
        ("em79xm12", "EM79xm12"),
    ],
)
def test_maidenhead_grid_normalization(
    raw_value: str,
    expected: str,
) -> None:
    """Grid locators should use conventional Maidenhead capitalization."""
    adapter = TypeAdapter(MaidenheadGrid)

    assert adapter.validate_python(raw_value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        "EM7",
        "SM79",
        "EM99zz",
        "EM79xm123",
        123,
    ],
)
def test_maidenhead_grid_rejects_invalid_values(value: object) -> None:
    """Grid locators must be valid 4-, 6-, or 8-character values."""
    adapter = TypeAdapter(MaidenheadGrid)

    with pytest.raises(ValidationError):
        adapter.validate_python(value)


def test_value_types_preserve_string_serialization() -> None:
    """Validated value types should remain plain strings at boundaries."""

    class ExampleModel(BaseModel):
        callsign: Callsign
        grid: MaidenheadGrid

    model = ExampleModel(
        callsign="ki5vnb/p",
        grid="em79XM",
    )

    assert model.model_dump(mode="json") == {
        "callsign": "KI5VNB/P",
        "grid": "EM79xm",
    }
