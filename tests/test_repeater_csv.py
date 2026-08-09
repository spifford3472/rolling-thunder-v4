"""Tests for strict local six-meter repeater CSV loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from rolling_thunder.repeater_csv import (
    DEFAULT_REPEATER_CSV_PATH,
    EXPECTED_REPEATER_CSV_HEADERS,
    RepeaterCsvRowError,
    RepeaterCsvSchemaError,
    load_repeater_csv,
)
from rolling_thunder.repeater_domain import RepeaterShiftDirection

APPROVED_SOURCE_SHA256 = "542ae7da9b3818c5f1ead8401b9c3bf025b0705450903c90d3e2c94ee2c4875f"


def csv_text(*rows: str) -> str:
    return ",".join(EXPECTED_REPEATER_CSV_HEADERS) + "\n" + "\n".join(rows) + "\n"


def test_parser_preserves_source_file_and_normalizes_typed_fields(tmp_path: Path) -> None:
    path = tmp_path / "6m_repeaters.csv"
    source = csv_text(
        "KA8ZXX Pleasant,Analogue,51.62,51.12,25,100,100,42.2458992,-84.40129852,6,Yes",
        "KI6SZ Fairborn,Analogue,51.66,50.66,25,,,39.82089996,-84.01940155,6,Yes",
    )
    path.write_text(source, encoding="utf-8")
    before = path.read_bytes()

    catalog = load_repeater_csv(path)

    assert path.read_bytes() == before
    assert len(catalog.repeaters) == 2
    first = catalog.repeaters[0]
    assert first.name == "KA8ZXX Pleasant"
    assert first.callsign == "KA8ZXX"
    assert first.rx_frequency.hz == 51_620_000
    assert first.tx_frequency.hz == 51_120_000
    assert first.shift_direction is RepeaterShiftDirection.MINUS
    assert first.offset_hz == 500_000
    assert str(first.rx_tone_hz) == "100"
    assert str(first.tx_tone_hz) == "100"
    assert catalog.repeaters[1].rx_tone_hz is None
    assert catalog.repeaters[1].tx_tone_hz is None


def test_parser_rejects_schema_drift(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text("Channel Name,Rx Frequency\nK1ABC Test,51.62\n", encoding="utf-8")

    with pytest.raises(RepeaterCsvSchemaError, match="approved schema"):
        load_repeater_csv(path)


@pytest.mark.parametrize(
    ("row", "message"),
    [
        (
            "K1ABC Test,Analogue,not-a-number,50.62,25,,,39.8,-84.0,6,Yes",
            "Rx Frequency must be numeric",
        ),
        (
            "K1ABC Test,Analogue,51.62,50.62,25,,,91,-84.0,6,Yes",
            "less than or equal to 90",
        ),
        (
            "K1ABC Test,Analogue,51.62,50.62,25,,,39.8,-84.0,6,Maybe",
            "Active must be Yes or No",
        ),
        (
            "K1ABC Test,Digital,51.62,50.62,25,,,39.8,-84.0,6,Yes",
            "Channel Type must be Analogue",
        ),
        (
            "K1ABC Test,Analogue,51.62,50.62,25,,,39.8,-84.0,2,Yes",
            "Band must be 6",
        ),
    ],
)
def test_parser_fails_closed_on_malformed_action_critical_values(
    tmp_path: Path,
    row: str,
    message: str,
) -> None:
    path = tmp_path / "bad.csv"
    path.write_text(csv_text(row), encoding="utf-8")

    with pytest.raises(RepeaterCsvRowError, match=message):
        load_repeater_csv(path)


def test_parser_rejects_duplicate_stable_identity(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.csv"
    path.write_text(
        csv_text(
            "KI6SZ Fairborn,Analogue,51.66,50.66,25,,,39.8209,-84.0194,6,Yes",
            "ki6sz   fairborn,Analogue,51.66,50.66,25,,,39.8209,-84.0194,6,Yes",
        ),
        encoding="utf-8",
    )

    with pytest.raises(RepeaterCsvRowError, match="stable identities must be unique"):
        load_repeater_csv(path)


def test_approved_local_source_matches_inspected_schema_when_present() -> None:
    """Run exact approved-source acceptance on anvilmobile without committing data."""
    if not DEFAULT_REPEATER_CSV_PATH.is_file():
        pytest.skip("approved local repeater deployment CSV is not present")

    catalog = load_repeater_csv(DEFAULT_REPEATER_CSV_PATH)

    assert catalog.source_sha256 == APPROVED_SOURCE_SHA256
    assert len(catalog.repeaters) == 66
    assert {record.channel_type.value for record in catalog.repeaters} == {"Analogue"}
    assert {record.bandwidth_khz for record in catalog.repeaters} == {25}
    assert {record.band_m for record in catalog.repeaters} == {6}
    assert all(record.source_active for record in catalog.repeaters)
    assert min(record.rx_frequency.hz for record in catalog.repeaters) == 51_620_000
    assert max(record.rx_frequency.hz for record in catalog.repeaters) == 53_970_000
