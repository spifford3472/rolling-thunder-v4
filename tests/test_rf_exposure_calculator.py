"""Offline unit matrix for antenna power and FCC RF-exposure calculator v1."""

from __future__ import annotations

import math
from uuid import UUID

import pytest
from pydantic import ValidationError

from rolling_thunder.antenna_reference_domain import (
    AntennaCatalogEntry,
    AntennaInstallation,
    BandAssociation,
    ExposureScenario,
    FrequencyRegion,
    FrequencySegment,
    GainSegment,
    GainUnit,
    GroundReflectionModel,
    InstallationBandAssignment,
    LossSegment,
    ModeProfile,
    TextProvenance,
)
from rolling_thunder.domain import DomainModel, Frequency
from rolling_thunder.rf_exposure_calculator import (
    CALCULATION_VERSION,
    ExposureEnvironment,
    calculate_rf_exposure,
    fcc_mpe_limit,
)

SOURCE = TextProvenance(source="offline test source")
ANTENNA_ID = UUID("00000000-0000-0000-0000-000000000101")
BAND_ID = UUID("00000000-0000-0000-0000-000000000102")
INSTALLATION_ID = UUID("00000000-0000-0000-0000-000000000103")
MODE_ID = UUID("00000000-0000-0000-0000-000000000104")


def segment(lower_hz: int = 50_000_000, upper_hz: int = 54_000_000) -> FrequencySegment:
    return FrequencySegment(lower=Frequency(hz=lower_hz), upper=Frequency(hz=upper_hz))


def complete_inputs(
    *,
    gain_db: float = 2.15,
    gain_unit: GainUnit = GainUnit.DBI,
    loss_db: float | None = 1.0,
    losses_complete: bool = True,
    frequency_hz: int = 52_000_000,
    controlled_tx_fraction: float = 0.5,
    uncontrolled_tx_fraction: float = 0.5,
    reflection: GroundReflectionModel = GroundReflectionModel.FREE_SPACE,
) -> tuple[AntennaCatalogEntry, AntennaInstallation, ModeProfile, ExposureScenario]:
    band = BandAssociation(
        association_id=BAND_ID,
        label="6 m",
        region=FrequencyRegion.VHF,
        frequencies=segment(),
        provenance=SOURCE,
    )
    catalog = AntennaCatalogEntry(
        antenna_id=ANTENNA_ID,
        name="Test antenna",
        provenance=SOURCE,
        bands=(band,),
        gains=(
            GainSegment(
                frequencies=segment(),
                gain_db=gain_db,
                unit=gain_unit,
                provenance=SOURCE,
            ),
        ),
    )
    installation = AntennaInstallation(
        installation_id=INSTALLATION_ID,
        antenna_id=ANTENNA_ID,
        name="Vehicle roof",
        location_description="Test-only roof position",
        losses_complete=losses_complete,
        loss_segments=(
            LossSegment(
                name="Explicit total path loss",
                frequencies=segment(),
                loss_db=loss_db,
                provenance=SOURCE,
            ),
        ),
        band_assignments=(
            InstallationBandAssignment(
                association_id=BAND_ID,
                active=True,
                provenance=SOURCE,
            ),
        ),
        provenance=SOURCE,
    )
    mode = ModeProfile(
        mode_profile_id=MODE_ID,
        name="Test mode",
        rf_envelope_duty=1.0,
        provenance=SOURCE,
    )
    scenario = ExposureScenario(
        installation_id=INSTALLATION_ID,
        mode_profile_id=MODE_ID,
        name="Test scenario",
        frequency=Frequency(hz=frequency_hz),
        forward_tx_watts=100.0,
        controlled_tx_fraction=controlled_tx_fraction,
        uncontrolled_tx_fraction=uncontrolled_tx_fraction,
        ground_reflection_model=reflection,
        provenance=SOURCE,
    )
    return catalog, installation, mode, scenario


@pytest.mark.parametrize(
    ("frequency_mhz", "controlled", "uncontrolled"),
    [
        (1.34, 100.0, 100.0),
        (3.0, 100.0, 20.0),
        (30.0, 1.0, 0.2),
        (50.0, 1.0, 0.2),
        (54.0, 1.0, 0.2),
        (146.0, 1.0, 0.2),
        (440.0, 440.0 / 300.0, 440.0 / 1500.0),
    ],
)
def test_fcc_table_boundaries(
    frequency_mhz: float, controlled: float, uncontrolled: float
) -> None:
    controlled_limit = fcc_mpe_limit(frequency_mhz, ExposureEnvironment.CONTROLLED)
    uncontrolled_limit = fcc_mpe_limit(frequency_mhz, ExposureEnvironment.UNCONTROLLED)

    assert controlled_limit.power_density_mw_cm2 == pytest.approx(controlled)
    assert controlled_limit.averaging_minutes == 6
    assert uncontrolled_limit.power_density_mw_cm2 == pytest.approx(uncontrolled)
    assert uncontrolled_limit.averaging_minutes == 30


@pytest.mark.parametrize("frequency_mhz", [math.nan, math.inf, -1.0, 0.0, 0.299, 100_001])
def test_fcc_table_rejects_invalid_frequency(frequency_mhz: float) -> None:
    with pytest.raises(ValueError):
        fcc_mpe_limit(frequency_mhz, ExposureEnvironment.UNCONTROLLED)


def test_calculator_applies_loss_gain_erp_and_separate_duty_factors() -> None:
    catalog, installation, mode, scenario = complete_inputs(
        controlled_tx_fraction=0.25, uncontrolled_tx_fraction=0.10
    )

    result = calculate_rf_exposure(
        catalog=catalog, installation=installation, mode=mode, scenario=scenario
    )

    antenna_watts = 100 * 10 ** (-1.0 / 10)
    expected_eirp = antenna_watts * 10 ** (2.15 / 10)
    assert result.calculation_version == CALCULATION_VERSION
    assert result.inputs_complete is True
    assert result.antenna_watts_peak == pytest.approx(antenna_watts)
    assert result.eirp_watts_peak == pytest.approx(expected_eirp)
    assert result.erp_watts_peak == pytest.approx(antenna_watts)
    assert result.controlled_time_average_eirp_watts == pytest.approx(expected_eirp * 0.25)
    assert result.uncontrolled_time_average_eirp_watts == pytest.approx(expected_eirp * 0.10)
    assert result.controlled is not None
    assert result.uncontrolled is not None
    assert result.needs_further_evaluation is True
    assert result.evaluated_distance_m == 1.8288
    assert result.distance_verified is False
    assert result.ground_reflection_model is GroundReflectionModel.FREE_SPACE
    assert result.ground_reflection_power_factor == 1.0
    assert all("is safe" not in caution.casefold() for caution in result.cautions)


def test_dbd_conversion_adds_2_15_db() -> None:
    catalog, installation, mode, scenario = complete_inputs(
        gain_db=0.0, gain_unit=GainUnit.DBD
    )
    result = calculate_rf_exposure(
        catalog=catalog, installation=installation, mode=mode, scenario=scenario
    )
    assert result.eirp_watts_peak == pytest.approx(
        100 * 10 ** (-1.0 / 10) * 10 ** (2.15 / 10)
    )


def test_unknown_loss_is_incomplete_and_never_treated_as_zero() -> None:
    catalog, installation, mode, scenario = complete_inputs(loss_db=None)
    result = calculate_rf_exposure(
        catalog=catalog, installation=installation, mode=mode, scenario=scenario
    )
    assert result.inputs_complete is False
    assert result.antenna_watts_peak is None
    assert any("losses are unknown" in item for item in result.missing_inputs)


def test_gain_is_not_interpolated_or_borrowed_from_other_frequency() -> None:
    catalog, installation, mode, scenario = complete_inputs(frequency_hz=52_000_000)
    catalog = catalog.model_copy(
        update={
            "gains": (
                GainSegment(
                    frequencies=segment(50_000_000, 51_000_000),
                    gain_db=2.15,
                    unit=GainUnit.DBI,
                    provenance=SOURCE,
                ),
            )
        }
    )
    result = calculate_rf_exposure(
        catalog=catalog, installation=installation, mode=mode, scenario=scenario
    )
    assert result.inputs_complete is False
    assert any("interpolation is forbidden" in item for item in result.missing_inputs)


def test_hf_catalog_does_not_imply_six_metre_support() -> None:
    catalog, installation, mode, scenario = complete_inputs()
    hf_band = BandAssociation(
        association_id=BAND_ID,
        label="HF",
        region=FrequencyRegion.HF,
        frequencies=segment(1_800_000, 30_000_000),
        provenance=SOURCE,
    )
    catalog = catalog.model_copy(update={"bands": (hf_band,)})
    result = calculate_rf_exposure(
        catalog=catalog, installation=installation, mode=mode, scenario=scenario
    )
    assert result.inputs_complete is False
    assert "frequency has no explicit antenna band association" in result.missing_inputs


def test_ground_reflection_assumption_is_explicit_and_changes_density() -> None:
    free_inputs = complete_inputs(reflection=GroundReflectionModel.FREE_SPACE)
    reflected_inputs = complete_inputs(
        reflection=GroundReflectionModel.ARRL_TYPICAL_GROUND
    )
    free = calculate_rf_exposure(
        catalog=free_inputs[0],
        installation=free_inputs[1],
        mode=free_inputs[2],
        scenario=free_inputs[3],
    )
    reflected = calculate_rf_exposure(
        catalog=reflected_inputs[0],
        installation=reflected_inputs[1],
        mode=reflected_inputs[2],
        scenario=reflected_inputs[3],
    )
    assert free.uncontrolled is not None
    assert reflected.uncontrolled is not None
    assert reflected.uncontrolled.estimated_power_density_mw_cm2 == pytest.approx(
        free.uncontrolled.estimated_power_density_mw_cm2 * 2.56
    )
    assert reflected.uncontrolled.estimated_required_distance_m == pytest.approx(
        free.uncontrolled.estimated_required_distance_m * math.sqrt(2.56)
    )


def test_mode_duty_and_default_distance_are_explicit_inputs() -> None:
    _, _, mode, scenario = complete_inputs()
    assert mode.rf_envelope_duty == 1.0
    assert scenario.occupant_distance_m == 1.8288
    assert scenario.occupant_distance_verified is False
    assert scenario.controlled_tx_fraction == 0.5
    assert scenario.uncontrolled_tx_fraction == 0.5


@pytest.mark.parametrize(
    ("model", "updates"),
    [
        (GainSegment, {"gain_db": math.nan}),
        (LossSegment, {"loss_db": -0.01}),
        (ModeProfile, {"rf_envelope_duty": 0.0}),
        (ExposureScenario, {"forward_tx_watts": 0.0}),
        (ExposureScenario, {"controlled_tx_fraction": math.inf}),
        (ExposureScenario, {"occupant_distance_m": 0.0}),
    ],
)
def test_models_reject_nonfinite_or_invalid_values(
    model: type[object], updates: dict[str, float]
) -> None:
    catalog, installation, mode, scenario = complete_inputs()
    source: DomainModel
    if model is GainSegment:
        source = catalog.gains[0]
    elif model is LossSegment:
        source = installation.loss_segments[0]
    elif model is ModeProfile:
        source = mode
    else:
        source = scenario
    with pytest.raises(ValidationError):
        type(source).model_validate(source.model_dump() | updates)


def test_six_metre_label_cannot_be_classified_as_hf() -> None:
    with pytest.raises(ValidationError, match="classified as VHF"):
        BandAssociation(
            label="6m",
            region=FrequencyRegion.HF,
            frequencies=segment(),
            provenance=SOURCE,
        )
