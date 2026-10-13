"""Validation for the manual YAML antenna-reference authority."""

from pathlib import Path

import pytest

from rolling_thunder.antenna_reference_config import load_antenna_reference_document
from rolling_thunder.antenna_reference_domain import ExposureDistanceKind, FrequencyRegion
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
