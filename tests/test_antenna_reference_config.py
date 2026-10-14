"""Validation for the manual YAML antenna-reference authority."""

from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from rolling_thunder.antenna_reference_config import (
    AntennaReferenceYamlSource,
    load_antenna_reference_document,
)
from rolling_thunder.antenna_reference_domain import ExposureDistanceKind, FrequencyRegion
from rolling_thunder.antenna_reference_service import AntennaReferenceService
from rolling_thunder.config import (
    ConfigurationFileError,
    ConfigurationValidationError,
)


def write_yaml(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "antenna-reference.yaml"
    path.write_text(content, encoding="utf-8")
    return path


VALID_YAML = """
schema_version: 1
catalog:
  - antenna_id: 10000000-0000-0000-0000-000000000001
    name: Reviewed antenna
    provenance: {source: manufacturer manual page 12}
    bands:
      - association_id: 20000000-0000-0000-0000-000000000001
        label: 6 m
        region: VHF
        frequencies: {lower: {hz: 50000000}, upper: {hz: 54000000}}
        provenance: {source: manufacturer manual page 12}
    gains:
      - gain_id: 30000000-0000-0000-0000-000000000001
        frequencies: {lower: {hz: 50000000}, upper: {hz: 54000000}}
        gain_db: 2.1
        unit: dBi
        provenance: {source: manufacturer manual page 12}
installations:
  - installation_id: 40000000-0000-0000-0000-000000000001
    antenna_id: 10000000-0000-0000-0000-000000000001
    name: Reviewed roof mount
    location_description: Documented roof position
    losses_complete: true
    loss_segments:
      - loss_id: 50000000-0000-0000-0000-000000000001
        name: Measured feed path
        frequencies: {lower: {hz: 50000000}, upper: {hz: 54000000}}
        loss_db: 1.2
        provenance: {source: retained VNA measurement}
    band_assignments:
      - assignment_id: 60000000-0000-0000-0000-000000000001
        association_id: 20000000-0000-0000-0000-000000000001
        active: true
        provenance: {source: installation review}
    provenance: {source: installation review}
mode_profiles:
  - mode_profile_id: 70000000-0000-0000-0000-000000000001
    name: 6 m FM
    rf_envelope_duty: 1.0
    provenance: {source: retained mode reference}
scenarios:
  - scenario_id: 80000000-0000-0000-0000-000000000001
    installation_id: 40000000-0000-0000-0000-000000000001
    mode_profile_id: 70000000-0000-0000-0000-000000000001
    name: Measured front seat
    frequency: {hz: 52525000}
    forward_tx_watts: 40
    controlled_tx_fraction: 0.25
    uncontrolled_tx_fraction: 0.05
    occupant_distance_m: 1.4
    occupant_distance_verified: true
    distance_kind: front_seat_measured
    ground_reflection_model: arrl_typical_ground
    provenance: {source: off-car reviewed scenario sheet}
"""


def test_empty_checked_in_example_contains_no_unverified_values() -> None:
    path = Path("config/antenna-reference.example.yaml")

    document = load_antenna_reference_document(path)

    assert document.catalog == ()
    assert document.installations == ()
    assert document.mode_profiles == ()
    assert document.scenarios == ()


def test_mobile_example_preserves_operator_claims_round_trips_and_stays_incomplete(
    tmp_path: Path,
) -> None:
    path = Path("config/antenna-reference.mobile-example.yaml")

    document = load_antenna_reference_document(path)

    assert [item.name for item in document.catalog] == [
        "Yaesu ATAS-120A",
        "Comet SBB-224",
        "144/430MHz VHF UHF Mobil Car Radio Antenna 2.15/3.5dBi VSWR <1.5",
    ]
    atas, comet, generic = document.catalog
    assert [(band.label, band.region, band.frequencies.lower.hz, band.frequencies.upper.hz) for band in atas.bands] == [
        ("40 m", FrequencyRegion.HF, 7_000_000, 7_300_000),
        ("20 m", FrequencyRegion.HF, 14_000_000, 14_350_000),
        ("15 m", FrequencyRegion.HF, 21_000_000, 21_450_000),
        ("10 m", FrequencyRegion.HF, 28_000_000, 29_700_000),
        ("6 m", FrequencyRegion.VHF, 50_000_000, 54_000_000),
    ]
    assert [gain.gain_db for gain in atas.gains] == [-10.0, -5.0, -5.0, -5.0, 0.0]
    assert "30 m, 17 m, and 12 m are intentionally omitted" in (atas.notes or "")
    assert comet.model == "SBB-224"
    assert len(comet.gains) == 1 and comet.gains[0].gain_db == 2.15 and comet.gains[0].unit.value == "dBi"
    assert generic.bands[0].frequencies.lower.hz == 420_000_000
    assert generic.bands[0].frequencies.upper.hz == 450_000_000
    assert generic.gains[0].gain_db == 3.5
    assert "pending datasheet" in (generic.gains[0].provenance.notes or "")

    assert all(item.losses_complete is False for item in document.installations)
    assert [[loss.name for loss in item.loss_segments] for item in document.installations] == [
        ["6.5 ft RG316 feedline"],
        ["6.5 ft RG316 feedline", "Comet CF-4160J duplexer", "2 ft RG8X feedline"],
        ["6 ft RG58 feedline", "Comet CF-4160J duplexer", "2 ft RG8X feedline"],
    ]
    assert all(
        loss.loss_db is None
        for installation in document.installations
        for loss in installation.loss_segments
    )
    assert all(
        item.location_description == "vehicle; only driver antenna distance measured"
        for item in document.installations
    )
    assert [item.provenance.notes for item in document.installations] == [
        "ONLY DRIVER antenna distance was physically measured as 90 in (2.286 m). No passenger positions available in normal use (front monitor; rear POTA equipment). Public separation is not verified.",
        "ONLY DRIVER antenna distance was physically measured as 64 in (1.6256 m). No passenger positions available in normal use (front monitor; rear POTA equipment). Public separation is not verified.",
        "ONLY DRIVER antenna distance was physically measured as 84 in (2.1336 m). No passenger positions available in normal use (front monitor; rear POTA equipment). Public separation is not verified.",
    ]
    assert [item.rf_envelope_duty for item in document.mode_profiles] == [0.5, 1.0, 1.0]
    assert document.mode_profiles[0].provenance.source  .startswith("ARRL heavily processed SSB")

    assert len(document.scenarios) == 22
    assert [(item.name, item.frequency.hz) for item in document.scenarios[:11]] == [
        ("ATAS-120A 40 m SSB maximum", 7_150_000),
        ("ATAS-120A 40 m FT8 maximum", 7_150_000),
        ("ATAS-120A 20 m SSB maximum", 14_175_000),
        ("ATAS-120A 20 m FT8 maximum", 14_175_000),
        ("ATAS-120A 15 m SSB maximum", 21_225_000),
        ("ATAS-120A 15 m FT8 maximum", 21_225_000),
        ("ATAS-120A 10 m SSB maximum", 28_850_000),
        ("ATAS-120A 10 m FT8 maximum", 28_850_000),
        ("ATAS-120A 6 m SSB maximum", 52_000_000),
                ("Comet SBB-224 2 m FM maximum", 146_000_000),
        ("Generic dual-band antenna operating 70 cm FM maximum", 435_000_000),
    ]
    assert [item.forward_tx_watts for item in document.scenarios[:11]] == [
        *([100.0, 70.0] * 4), 100.0, 15.0, 15.0,
    ]
    assert all(item.controlled_tx_fraction == 0.5 for item in document.scenarios)
    assert all(item.uncontrolled_tx_fraction == 0.5 for item in document.scenarios)
    assert all(
        item.distance_kind is ExposureDistanceKind.FRONT_SEAT_MEASURED
        and item.occupant_distance_verified is True
        for item in document.scenarios[:11]
    )
    assert [item.occupant_distance_m for item in document.scenarios[:11]] == [
        *([2.286] * 9),
        1.6256,
        2.1336,
    ]

    round_trip_path = tmp_path / "mobile-round-trip.yaml"
    round_trip_path.write_text(
        yaml.safe_dump(yaml.safe_load(path.read_text(encoding="utf-8")), sort_keys=False),
        encoding="utf-8",
    )
    assert load_antenna_reference_document(round_trip_path) == document

    publication = AntennaReferenceService(AntennaReferenceYamlSource(path)).load_publication()
    assert len(publication.evaluations) == 22
    assert all(result.result.inputs_complete is False for result in publication.evaluations)
    assert all(result.result.needs_further_evaluation is True for result in publication.evaluations)
    assert all(result.zero_loss_screening is not None for result in publication.evaluations)
    assert all(
        result.zero_loss_screening is not None
        and result.zero_loss_screening.uncontrolled is not None
        for result in publication.evaluations
    )
    public_vhf = next(
        result for result in publication.evaluations
        if result.scenario.name == "Comet SBB-224 2 m FM maximum (hypothetical public 6 ft)"
    )
    assert public_vhf.zero_loss_screening is not None
    assert public_vhf.zero_loss_screening.uncontrolled is not None
    assert 3.6 < public_vhf.zero_loss_screening.uncontrolled.estimated_required_distance_m / 0.3048 < 3.8
    from rolling_thunder.antenna_reference_ui import scenario_evaluation_lines
    rendered = "\n".join(scenario_evaluation_lines(public_vhf))
    assert "BASED ON ARRL RF EXPOSURE CALCULATOR" in rendered
    assert "ASSUMPTION: 0 dB CABLE/DUPLEXER LOSS" in rendered
    assert "INCOMPLETE" not in rendered
    assert "NOT AN FCC COMPLIANCE DETERMINATION" in rendered
    from rolling_thunder.antenna_reference_panel import build_reference_cards
    from rolling_thunder.antenna_reference_ui import (
        PUBLIC_TABLE_COLUMNS,
        compact_public_table_lines,
        public_table_rows,
    )
    card = next(
        card for card in build_reference_cards(publication.snapshot, publication.evaluations)
        if "SBB-224" in card.antenna_name
    )
    table = "\n".join(compact_public_table_lines(card))
    assert "PUBLIC MIN" in table
    assert "15 W" in table
    assert "3.7 ft" in table
    assert "DRIVER" not in table
    assert "INCOMPLETE" not in table

    atas_cards = [
        item
        for item in build_reference_cards(publication.snapshot, publication.evaluations)
        if item.antenna_name == "Yaesu ATAS-120A"
    ]
    atas_card = replace(
        atas_cards[0],
        evaluations=tuple(
            evaluation
            for atas_region_card in atas_cards
            for evaluation in atas_region_card.evaluations
        ),
    )
    rows = public_table_rows(atas_card)
    assert PUBLIC_TABLE_COLUMNS == ("BAND", "MODE", "POWER", "PUBLIC MIN")
    assert len(rows) == 9
    assert [row.band for row in rows] == [
        "40m",
        "40m",
        "20m",
        "20m",
        "15m",
        "15m",
        "10m",
        "10m",
        "6m",
    ]
    assert all(len(row.cells) == len(PUBLIC_TABLE_COLUMNS) for row in rows)
    assert all(
        len(row.public_minimum.removesuffix(" ft").partition(".")[2]) == 1
        for row in rows
    )
    assert (rows[-1].band, rows[-1].mode) == ("6m", "SSB")

    assert all(result.result.controlled is None for result in publication.evaluations)
    assert all(result.result.uncontrolled is None for result in publication.evaluations)
    assert [result.result.evaluated_distance_m for result in publication.evaluations[:11]] == [
        *([2.286] * 9),
        1.6256,
        2.1336,
    ]
    assert all(result.result.distance_verified is True for result in publication.evaluations[:11])
    assert all(item.distance_kind is ExposureDistanceKind.HYPOTHETICAL_SIX_FOOT and item.occupant_distance_verified is False and item.occupant_distance_m == 1.8288 for item in document.scenarios[11:])
    assert all(result.result.distance_verified is False for result in publication.evaluations[11:])
    assert "0.1 dB" in (document.installations[1].loss_segments[1].provenance.notes or "")
    assert "0.2 dB" in (document.installations[2].loss_segments[1].provenance.notes or "")
    assert all(
        "installation loss inventory is not marked complete" in result.result.missing_inputs
        and "one or more applicable installation losses are unknown"
        in result.result.missing_inputs
        for result in publication.evaluations
    )


def test_dense_1280x720_budget_keeps_all_nine_rows_accessible_above_footer() -> None:
    from rolling_thunder.antenna_reference_ui import (
        antenna_vertical_budget,
        public_table_layout,
        public_table_row_bounds,
        tk_label_required_height_px,
    )

    row_labels = (
        "40m SSB",
        "40m FT8",
        "20m SSB",
        "20m FT8",
        "15m SSB",
        "15m FT8",
        "10m SSB",
        "10m FT8",
        "6m SSB",
    )
    dense_budget = antenna_vertical_budget(720, pixels_per_inch=96.0)
    assert dense_budget.display_height_px == 720
    assert dense_budget.table_usable_height_px == 475

    dense_layout = public_table_layout(
        dense_budget.table_usable_height_px,
        len(row_labels),
        pixels_per_inch=96.0,
    )
    assert dense_layout.heading_font_size == 17
    assert dense_layout.row_font_size == 20
    assert dense_layout.required_height_px <= dense_budget.table_usable_height_px

    row_bounds = public_table_row_bounds(dense_layout, len(row_labels))
    assert len(row_bounds) == len(row_labels) == 9
    assert all(
        bottom - top
        >= tk_label_required_height_px(
            dense_layout.row_font_size + 1,
            pixels_per_inch=96.0,
        )
        for top, bottom in row_bounds
    )
    footer_top = dense_layout.required_height_px - dense_layout.footer_height_px
    accessible_rows = tuple(
        label
        for label, (top, bottom) in zip(row_labels, row_bounds, strict=True)
        if 0 <= top < bottom <= footer_top
    )
    assert accessible_rows == row_labels
    assert row_bounds[-1][1] <= footer_top < dense_budget.table_usable_height_px


def test_full_yaml_preserves_provenance_six_metres_and_measured_distance(
    tmp_path: Path,
) -> None:
    document = load_antenna_reference_document(write_yaml(tmp_path, VALID_YAML))

    assert document.catalog[0].bands[0].region is FrequencyRegion.VHF
    assert document.catalog[0].gains[0].provenance.source == "manufacturer manual page 12"
    assert document.installations[0].loss_segments[0].loss_db == 1.2
    assert document.scenarios[0].distance_kind is ExposureDistanceKind.FRONT_SEAT_MEASURED
    assert document.scenarios[0].occupant_distance_verified is True
    assert document.scenarios[0].controlled_tx_fraction == 0.25
    assert document.scenarios[0].uncontrolled_tx_fraction == 0.05


def test_unknown_cross_reference_rejects_entire_snapshot(tmp_path: Path) -> None:
    invalid = VALID_YAML.replace(
        "installation_id: 40000000-0000-0000-0000-000000000001\n    mode_profile_id",
        "installation_id: 49999999-0000-0000-0000-000000000001\n    mode_profile_id",
    )

    with pytest.raises(ConfigurationValidationError, match="unknown installation"):
        load_antenna_reference_document(write_yaml(tmp_path, invalid))


def test_scenario_cannot_inherit_reflection_or_distance_defaults(tmp_path: Path) -> None:
    invalid = VALID_YAML.replace(
        "    ground_reflection_model: arrl_typical_ground\n",
        "",
    )

    with pytest.raises(ConfigurationValidationError, match="ground_reflection_model"):
        load_antenna_reference_document(write_yaml(tmp_path, invalid))


def test_front_seat_distance_must_be_measured(tmp_path: Path) -> None:
    invalid = VALID_YAML.replace("occupant_distance_verified: true", "occupant_distance_verified: false")

    with pytest.raises(ConfigurationValidationError, match="must be measured/verified"):
        load_antenna_reference_document(write_yaml(tmp_path, invalid))


def test_public_distance_is_independently_typed_and_measured(tmp_path: Path) -> None:
    public_yaml = VALID_YAML.replace("Measured front seat", "Measured public point").replace(
        "front_seat_measured", "public_measured"
    )

    document = load_antenna_reference_document(write_yaml(tmp_path, public_yaml))

    assert document.scenarios[0].distance_kind is ExposureDistanceKind.PUBLIC_MEASURED
    assert document.scenarios[0].occupant_distance_m == 1.4


def test_hypothetical_distance_must_remain_exactly_six_feet(tmp_path: Path) -> None:
    invalid = VALID_YAML.replace("occupant_distance_verified: true", "occupant_distance_verified: false").replace(
        "distance_kind: front_seat_measured", "distance_kind: hypothetical_six_foot"
    )

    with pytest.raises(ConfigurationValidationError, match="exactly 1.8288 m"):
        load_antenna_reference_document(write_yaml(tmp_path, invalid))


def test_missing_authority_file_is_an_explicit_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationFileError, match="was not found"):
        load_antenna_reference_document(tmp_path / "missing.yaml")
