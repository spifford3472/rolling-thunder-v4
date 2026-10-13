"""Typed application boundary for future antenna-reference presentation/control."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from rolling_thunder.antenna_reference_domain import (
    AntennaCatalogEntry,
    AntennaInstallation,
    ExposureScenario,
    ModeProfile,
)
from rolling_thunder.rf_exposure_calculator import RfExposureResult, calculate_rf_exposure


class AntennaReferenceStore(Protocol):
    """Persistence operations required by the application boundary."""

    def save_catalog(self, catalog: AntennaCatalogEntry) -> None: ...

    def get_catalog(self, antenna_id: UUID) -> AntennaCatalogEntry | None: ...

    def save_installation(self, installation: AntennaInstallation) -> None: ...

    def get_installation(self, installation_id: UUID) -> AntennaInstallation | None: ...

    def save_mode_profile(self, profile: ModeProfile) -> None: ...

    def get_mode_profile(self, profile_id: UUID) -> ModeProfile | None: ...

    def save_scenario(self, scenario: ExposureScenario) -> None: ...

    def get_scenario(self, scenario_id: UUID) -> ExposureScenario | None: ...


class AntennaReferenceNotFoundError(LookupError):
    """Raised when an evaluation aggregate is missing from offline storage."""


class AntennaReferenceService:
    """Hardware-free controller/service boundary with no radio actuation methods."""

    def __init__(self, store: AntennaReferenceStore) -> None:
        self._store = store

    def save_catalog(self, catalog: AntennaCatalogEntry) -> None:
        self._store.save_catalog(catalog)

    def save_installation(self, installation: AntennaInstallation) -> None:
        self._store.save_installation(installation)

    def save_mode_profile(self, profile: ModeProfile) -> None:
        self._store.save_mode_profile(profile)

    def save_scenario(self, scenario: ExposureScenario) -> None:
        self._store.save_scenario(scenario)

    def evaluate_scenario(self, scenario_id: UUID) -> RfExposureResult:
        """Load immutable inputs and run the pure versioned calculator."""
        scenario = self._store.get_scenario(scenario_id)
        if scenario is None:
            raise AntennaReferenceNotFoundError(f"RF exposure scenario not found: {scenario_id}")
        installation = self._store.get_installation(scenario.installation_id)
        if installation is None:
            raise AntennaReferenceNotFoundError(
                f"Antenna installation not found: {scenario.installation_id}"
            )
        catalog = self._store.get_catalog(installation.antenna_id)
        if catalog is None:
            raise AntennaReferenceNotFoundError(
                f"Antenna catalog entry not found: {installation.antenna_id}"
            )
        mode = self._store.get_mode_profile(scenario.mode_profile_id)
        if mode is None:
            raise AntennaReferenceNotFoundError(
                f"Antenna mode profile not found: {scenario.mode_profile_id}"
            )
        return calculate_rf_exposure(
            catalog=catalog,
            installation=installation,
            mode=mode,
            scenario=scenario,
        )
