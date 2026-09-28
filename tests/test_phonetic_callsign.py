"""Tests for deterministic phonetic callsign parsing."""

import pytest

from rolling_thunder.phonetic_callsign import (
    is_structurally_valid_callsign,
    normalize_token,
    parse_phonetic_callsign,
)


@pytest.mark.parametrize(
    ("tokens", "expected"),
    [
        (
            ["KILO", "INDIA", "FIVE", "VICTOR", "NOVEMBER", "BRAVO"],
            "KI5VNB",
        ),
        (
            ["GOLF", "BRAVO", "NINER", "ZERO", "MIKE", "GOLF", "YANKEE"],
            "GB90MGY",
        ),
        (
            [
                "KILO",
                "INDIA",
                "FIVE",
                "VICTOR",
                "NOVEMBER",
                "BRAVO",
                "SLASH",
                "VICTOR",
                "ECHO",
                "SIX",
            ],
            "KI5VNB/VE6",
        ),
        (
            ["KILO", "ITALY", "FIVE", "VICTORIA", "NOVEMBER", "BRAVO"],
            "KI5VNB",
        ),
        (
            ["KILO", "INDIA", "FIVE", "SUGAR", "NOVEMBER", "BRAVO"],
            "KI5SNB",
        ),
        (
            ["QUEEN", "ONE", "ZANSABAR", "PORTABLE"],
            "Q1Z/P",
        ),
        (
            ["NOVEMBER", "CHARLIE", "FOUR", "X", "RAY", "LIMA"],
            "NC4XL",
        ),
    ],
)
def test_parses_supported_phonetic_aliases(tokens: list[str], expected: str) -> None:
    result = parse_phonetic_callsign(tokens)

    assert result.callsign == expected
    assert result.unknown_tokens == ()
    assert result.is_valid is True


def test_unknown_token_disables_result_without_guessing() -> None:
    result = parse_phonetic_callsign(
        ["KILO", "INDIA", "FIVE", "MYSTERY", "NOVEMBER", "BRAVO"]
    )

    assert result.callsign is None
    assert result.unknown_tokens == ("MYSTERY",)
    assert result.is_valid is False


@pytest.mark.parametrize(
    ("tokens", "unknown"),
    [
        (["NOVEMBER", "CHARLIE", "FOUR", "X", "LIMA"], ("X",)),
        (["NOVEMBER", "CHARLIE", "FOUR", "RAY", "LIMA"], ("RAY",)),
    ],
)
def test_incomplete_x_ray_pair_is_rejected(
    tokens: list[str],
    unknown: tuple[str, ...],
) -> None:
    result = parse_phonetic_callsign(tokens)

    assert result.callsign is None
    assert result.unknown_tokens == unknown
    assert result.is_valid is False


@pytest.mark.parametrize(
    "tokens",
    [
        ["KILO", "INDIA", "VICTOR", "NOVEMBER", "BRAVO"],
        ["FIVE", "SIX", "SEVEN"],
        ["KILO", "INDIA", "FIVE", "SLASH"],
        ["SLASH", "KILO", "INDIA", "FIVE"],
    ],
)
def test_structurally_invalid_output_is_rejected(tokens: list[str]) -> None:
    result = parse_phonetic_callsign(tokens)

    assert result.callsign is None
    assert result.unknown_tokens == ()
    assert result.is_valid is False


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("  victor  ", "VICTOR"),
        ("x_ray", "X-RAY"),
        ("Zulu", "ZULU"),
    ],
)
def test_normalize_token(value: str, expected: str) -> None:
    assert normalize_token(value) == expected


@pytest.mark.parametrize(
    ("callsign", "expected"),
    [
        ("KI5VNB", True),
        ("GB90MGY", True),
        ("KI5VNB/VE6", True),
        ("KI5VNB/P", True),
        ("KI/VNB", False),
        ("KI5VNB/", False),
        ("KI5VNB?", False),
        ("12345", False),
    ],
)
def test_structural_validation(callsign: str, expected: bool) -> None:
    assert is_structurally_valid_callsign(callsign) is expected
