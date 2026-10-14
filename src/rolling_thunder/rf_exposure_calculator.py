"""Versioned, pure RF power and FCC MPE advisory calculations."""

from __future__ import annotations

import math
from enum import StrEnum
from typing import Final

from pydantic import Field

from rolling_thunder.antenna_reference_domain import (
    AntennaCatalogEntry,
    AntennaInstallation,
    ExposureScenario,
    GainSegment,
    GroundReflectionModel,
    LossSegment,
    ModeProfile,
)
from rolling_thunder.domain import DomainModel

CALCULATION_VERSION: Final = "rf-exposure-plane-wave-v1"
FCC_CITATION: Final = "47 CFR 1.1310(e)(1), Table 1 (eCFR checked 2026-10-12)"
ARRL_CITATION: Final = "ARRL RF Exposure Calculator and instructions (checked 2026-10-12)"


class ExposureEnvironment(StrEnum):
    """FCC MPE exposure environment."""

    CONTROLLED = "controlled"
    UNCONTROLLED = "uncontrolled"


class MpeLimit(DomainModel):
    """Frequency-specific FCC plane-wave-equivalent MPE limit."""

    environment: ExposureEnvironment
    frequency_mhz: float = Field(gt=0, allow_inf_nan=False)
    power_density_mw_cm2: float = Field(gt=0, allow_inf_nan=False)
    averaging_minutes: int = Field(gt=0)
    citation: str


class ExposureEstimate(DomainModel):
    """One numerical estimate; it intentionally carries no pass/safe verdict."""

    limit: MpeLimit
    estimated_power_density_mw_cm2: float = Field(ge=0, allow_inf_nan=False)
    estimated_required_distance_m: float = Field(ge=0, allow_inf_nan=False)


class RfExposureResult(DomainModel):
    """Immutable calculator result with explicit incompleteness and uncertainty."""

    calculation_version: str
    citations: tuple[str, ...]
    inputs_complete: bool
    missing_inputs: tuple[str, ...]
    evaluated_distance_m: float = Field(gt=0, allow_inf_nan=False)
    distance_verified: bool
    ground_reflection_model: GroundReflectionModel
    ground_reflection_power_factor: float = Field(ge=1, allow_inf_nan=False)
    antenna_watts_peak: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    eirp_watts_peak: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    erp_watts_peak: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    controlled_time_average_eirp_watts: float | None = Field(
        default=None, ge=0, allow_inf_nan=False
    )
    uncontrolled_time_average_eirp_watts: float | None = Field(
        default=None, ge=0, allow_inf_nan=False
    )
    controlled: ExposureEstimate | None = None
    uncontrolled: ExposureEstimate | None = None
    needs_further_evaluation: bool = True
    cautions: tuple[str, ...]


def fcc_mpe_limit(frequency_mhz: float, environment: ExposureEnvironment) -> MpeLimit:
    """Return the exact Table 1 piecewise power-density limit for 0.3-100000 MHz."""
    if not math.isfinite(frequency_mhz) or not 0.3 <= frequency_mhz <= 100_000:
        raise ValueError("FCC MPE frequency must be finite and within 0.3-100000 MHz")

    if environment is ExposureEnvironment.CONTROLLED:
        if frequency_mhz <= 3:
            density = 100.0
        elif frequency_mhz <= 30:
            density = 900.0 / frequency_mhz**2
        elif frequency_mhz <= 300:
            density = 1.0
        elif frequency_mhz <= 1_500:
            density = frequency_mhz / 300.0
        else:
            density = 5.0
        averaging = 6
    else:
        if frequency_mhz <= 1.34:
            density = 100.0
        elif frequency_mhz <= 30:
            density = 180.0 / frequency_mhz**2
        elif frequency_mhz <= 300:
            density = 0.2
        elif frequency_mhz <= 1_500:
            density = frequency_mhz / 1_500.0
        else:
            density = 1.0
        averaging = 30

    return MpeLimit(
        environment=environment,
        frequency_mhz=frequency_mhz,
        power_density_mw_cm2=density,
        averaging_minutes=averaging,
        citation=FCC_CITATION,
    )


def _single_gain(
    catalog: AntennaCatalogEntry, scenario: ExposureScenario
) -> GainSegment | None:
    matches = tuple(item for item in catalog.gains if item.frequencies.contains(scenario.frequency))
    return matches[0] if len(matches) == 1 else None


def _applicable_losses(
    installation: AntennaInstallation, scenario: ExposureScenario
) -> tuple[LossSegment, ...]:
    return tuple(
        item for item in installation.loss_segments if item.frequencies.contains(scenario.frequency)
    )


def calculate_rf_exposure(
    *,
    catalog: AntennaCatalogEntry,
    installation: AntennaInstallation,
    mode: ModeProfile,
    scenario: ExposureScenario,
) -> RfExposureResult:
    """Calculate an advisory far-field estimate without hardware or mutable state."""
    missing: list[str] = []
    if installation.antenna_id != catalog.antenna_id:
        missing.append("installation does not reference the supplied antenna")
    if scenario.installation_id != installation.installation_id:
        missing.append("scenario does not reference the supplied installation")
    if scenario.mode_profile_id != mode.mode_profile_id:
        missing.append("scenario does not reference the supplied mode profile")

    matching_bands = {
        band.association_id
        for band in catalog.bands
        if band.frequencies.contains(scenario.frequency)
    }
    active_bands = {
        assignment.association_id
        for assignment in installation.band_assignments
        if assignment.active
    }
    if not matching_bands:
        missing.append("frequency has no explicit antenna band association")
    elif not matching_bands.intersection(active_bands):
        missing.append("frequency has no active installation band assignment")

    gain = _single_gain(catalog, scenario)
    gain_match_count = sum(
        item.frequencies.contains(scenario.frequency) for item in catalog.gains
    )
    if gain is None:
        if gain_match_count == 0:
            missing.append("antenna gain is unknown at this frequency; interpolation is forbidden")
        else:
            missing.append("multiple antenna gain records apply at this frequency")

    losses = _applicable_losses(installation, scenario)
    if not installation.losses_complete:
        missing.append("installation loss inventory is not marked complete")
    if not losses:
        missing.append("no explicit installation loss record applies at this frequency")
    elif any(item.loss_db is None for item in losses):
        missing.append("one or more applicable installation losses are unknown")

    frequency_mhz = scenario.frequency.mhz
    controlled_limit = fcc_mpe_limit(frequency_mhz, ExposureEnvironment.CONTROLLED)
    uncontrolled_limit = fcc_mpe_limit(frequency_mhz, ExposureEnvironment.UNCONTROLLED)
    cautions = (
        "This is a plane-wave/far-field approximation, not a compliance or safety determination.",
        "Near-field coupling and vehicle body, roof, glass, occupants, feedline, and metal can change fields.",
        "Aggregate exposure from all simultaneously operating RF sources requires a separate evaluation.",
        "Antenna pattern direction and the real driver, passenger, and bystander geometry are not modeled.",
        "Validate installation-specific results against current FCC/ARRL guidance and bench or field data.",
        (
            "The 6 ft (1.8288 m) default is only a scenario value and is not a verified vehicle "
            "clearance."
        ),
    )

    if missing or gain is None:
        return RfExposureResult(
            calculation_version=CALCULATION_VERSION,
            citations=(FCC_CITATION, ARRL_CITATION),
            inputs_complete=False,
            missing_inputs=tuple(missing),
            evaluated_distance_m=scenario.occupant_distance_m,
            distance_verified=scenario.occupant_distance_verified,
            ground_reflection_model=scenario.ground_reflection_model,
            ground_reflection_power_factor=(
                scenario.ground_reflection_model.power_density_factor
            ),
            cautions=cautions,
        )

    total_loss_db = sum(item.loss_db for item in losses if item.loss_db is not None)
    antenna_watts = scenario.forward_tx_watts * 10 ** (-total_loss_db / 10)
    eirp_watts = antenna_watts * 10 ** (gain.gain_dbi / 10)
    erp_watts = eirp_watts / 10 ** (2.15 / 10)
    controlled_average_eirp = (
        eirp_watts * mode.rf_envelope_duty * scenario.controlled_tx_fraction
    )
    uncontrolled_average_eirp = (
        eirp_watts * mode.rf_envelope_duty * scenario.uncontrolled_tx_fraction
    )
    reflection_factor = scenario.ground_reflection_model.power_density_factor

    def estimate(limit: MpeLimit, average_eirp: float) -> ExposureEstimate:
        # W/m^2 converts to mW/cm^2 by multiplying by 0.1.
        density = (
            average_eirp
            * reflection_factor
            / (4 * math.pi * scenario.occupant_distance_m**2)
            * 0.1
        )
        limit_w_m2 = limit.power_density_mw_cm2 * 10
        distance = math.sqrt(average_eirp * reflection_factor / (4 * math.pi * limit_w_m2))
        return ExposureEstimate(
            limit=limit,
            estimated_power_density_mw_cm2=density,
            estimated_required_distance_m=distance,
        )

    return RfExposureResult(
        calculation_version=CALCULATION_VERSION,
        citations=(FCC_CITATION, ARRL_CITATION),
        inputs_complete=True,
        missing_inputs=(),
        evaluated_distance_m=scenario.occupant_distance_m,
        distance_verified=scenario.occupant_distance_verified,
        ground_reflection_model=scenario.ground_reflection_model,
        ground_reflection_power_factor=reflection_factor,
        antenna_watts_peak=antenna_watts,
        eirp_watts_peak=eirp_watts,
        erp_watts_peak=erp_watts,
        controlled_time_average_eirp_watts=controlled_average_eirp,
        uncontrolled_time_average_eirp_watts=uncontrolled_average_eirp,
        controlled=estimate(controlled_limit, controlled_average_eirp),
        uncontrolled=estimate(uncontrolled_limit, uncontrolled_average_eirp),
        cautions=cautions,
    )
