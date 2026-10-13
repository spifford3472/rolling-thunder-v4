"""Read-only application boundary for antenna-reference publication."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from rolling_thunder.antenna_reference_domain import (
    AntennaCatalogEntry,
    AntennaInstallation,
    ExposureScenario,
    ModeProfile,
)
from rolling_thunder.rf_exposure_calculator import RfExposureResult, calculate_rf_exposure


@dataclass(frozen=True)
class AntennaReferenceSnapshot:
    """One immutable source-of-truth snapshot loaded from manual configuration."""

    catalog: tuple[AntennaCatalogEntry, ...] = ()
    installations: tuple[AntennaInstallation, ...] = ()
    mode_profiles: tuple[ModeProfile, ...] = ()
    scenarios: tuple[ExposureScenario, ...] = ()


class AntennaReferenceSource(Protocol):
    """Read-only authority required by the application service."""

    def load_snapshot(self) -> AntennaReferenceSnapshot: ...


@dataclass(frozen=True)
class AntennaScenarioEvaluation:
    """A configured scenario and its immutable advisory result."""

    scenario: ExposureScenario
    mode: ModeProfile
    result: RfExposureResult


@dataclass(frozen=True)
class AntennaReferencePublication:
    """Atomic snapshot plus all calculations derived from that exact snapshot."""

    snapshot: AntennaReferenceSnapshot
    evaluations: tuple[AntennaScenarioEvaluation, ...] = ()


class AntennaReferenceService:
    """Load manual configuration and calculate it without mutation or radio authority."""

    def __init__(self, source: AntennaReferenceSource) -> None:
        self._source = source

    def load_publication(self) -> AntennaReferencePublication:
        """Load and evaluate one whole source snapshot for atomic publication."""
        snapshot = self._source.load_snapshot()
        catalog_by_id = {item.antenna_id: item for item in snapshot.catalog}
        installation_by_id = {
            item.installation_id: item for item in snapshot.installations
        }
        mode_by_id = {item.mode_profile_id: item for item in snapshot.mode_profiles}
        evaluations: list[AntennaScenarioEvaluation] = []
        for scenario in snapshot.scenarios:
            installation = installation_by_id[scenario.installation_id]
            catalog = catalog_by_id[installation.antenna_id]
            mode = mode_by_id[scenario.mode_profile_id]
            evaluations.append(
                AntennaScenarioEvaluation(
                    scenario=scenario,
                    mode=mode,
                    result=self.evaluate_inputs(
                        catalog=catalog,
                        installation=installation,
                        mode=mode,
                        scenario=scenario,
                    ),
                )
            )
        return AntennaReferencePublication(
            snapshot=snapshot,
            evaluations=tuple(evaluations),
        )

    @staticmethod
    def evaluate_inputs(
        *,
        catalog: AntennaCatalogEntry,
        installation: AntennaInstallation,
        mode: ModeProfile,
        scenario: ExposureScenario,
    ) -> RfExposureResult:
        """Evaluate already-loaded immutable inputs without persistence or hardware."""
        return calculate_rf_exposure(
            catalog=catalog,
            installation=installation,
            mode=mode,
            scenario=scenario,
        )
