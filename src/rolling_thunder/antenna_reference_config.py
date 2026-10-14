"""Typed YAML authority for read-only antenna and RF-exposure reference data."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import ValidationError, model_validator

from rolling_thunder.antenna_reference_domain import (
    AntennaCatalogEntry,
    AntennaInstallation,
    ExposureScenario,
    ModeProfile,
)
from rolling_thunder.antenna_reference_service import AntennaReferenceSnapshot
from rolling_thunder.config import (
    ConfigurationFileError,
    ConfigurationModel,
    ConfigurationParseError,
    ConfigurationValidationError,
)


class AntennaReferenceDocument(ConfigurationModel):
    """One complete, immutable, manually maintained authority snapshot."""

    schema_version: Literal[1]
    catalog: tuple[AntennaCatalogEntry, ...] = ()
    installations: tuple[AntennaInstallation, ...] = ()
    mode_profiles: tuple[ModeProfile, ...] = ()
    scenarios: tuple[ExposureScenario, ...] = ()

    @model_validator(mode="after")
    def validate_references(self) -> AntennaReferenceDocument:
        antenna_ids = [item.antenna_id for item in self.catalog]
        installation_ids = [item.installation_id for item in self.installations]
        mode_ids = [item.mode_profile_id for item in self.mode_profiles]
        scenario_ids = [item.scenario_id for item in self.scenarios]
        for label, values in (
            ("catalog antenna", antenna_ids),
            ("installation", installation_ids),
            ("mode profile", mode_ids),
            ("scenario", scenario_ids),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{label} UUIDs must be unique")

        catalog_by_id = {item.antenna_id: item for item in self.catalog}
        installation_by_id = {
            item.installation_id: item for item in self.installations
        }
        mode_by_id = {item.mode_profile_id: item for item in self.mode_profiles}
        for installation in self.installations:
            catalog = catalog_by_id.get(installation.antenna_id)
            if catalog is None:
                raise ValueError(
                    f"installation {installation.installation_id} references an unknown antenna"
                )
            valid_associations = {item.association_id for item in catalog.bands}
            for assignment in installation.band_assignments:
                if "active" not in assignment.model_fields_set:
                    raise ValueError(
                        f"installation {installation.installation_id} band assignment "
                        "must explicitly set active"
                    )
                if assignment.association_id not in valid_associations:
                    raise ValueError(
                        f"installation {installation.installation_id} assigns band "
                        f"{assignment.association_id} not owned by its antenna"
                    )
        for scenario in self.scenarios:
            required_explicit = {
                "occupant_distance_m",
                "occupant_distance_verified",
                "distance_kind",
                "ground_reflection_model",
            }
            omitted = sorted(required_explicit - scenario.model_fields_set)
            if omitted:
                raise ValueError(
                    f"scenario {scenario.scenario_id} must explicitly set: "
                    + ", ".join(omitted)
                )
            if scenario.installation_id not in installation_by_id:
                raise ValueError(
                    f"scenario {scenario.scenario_id} references an unknown installation"
                )
            if scenario.mode_profile_id not in mode_by_id:
                raise ValueError(
                    f"scenario {scenario.scenario_id} references an unknown mode profile"
                )
        return self

    def snapshot(self) -> AntennaReferenceSnapshot:
        """Publish one atomic immutable domain snapshot."""
        return AntennaReferenceSnapshot(
            catalog=self.catalog,
            installations=self.installations,
            mode_profiles=self.mode_profiles,
            scenarios=self.scenarios,
        )


def _validation_details(error: ValidationError) -> str:
    return "\n".join(
        f"- {'.'.join(str(part) for part in item['loc']) or '<document>'}: "
        f"{item['msg']}"
        for item in error.errors(include_url=False)
    )


def load_antenna_reference_document(path: Path) -> AntennaReferenceDocument:
    """Read and strictly validate one antenna authority YAML document."""
    try:
        yaml_text = path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise ConfigurationFileError(
            f"Antenna reference file was not found: {path}. "
            "Copy config/antenna-reference.example.yaml and add only sourced values."
        ) from error
    except OSError as error:
        raise ConfigurationFileError(
            f"Antenna reference file could not be read: {path}: {error}"
        ) from error

    try:
        raw: Any = yaml.safe_load(yaml_text)
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        location = (
            f"line {mark.line + 1}, column {mark.column + 1}"
            if mark is not None
            else "an unknown location"
        )
        problem = getattr(error, "problem", None) or str(error)
        raise ConfigurationParseError(
            f"Antenna reference YAML is invalid at {location}: {problem}"
        ) from error
    if not isinstance(raw, dict):
        raise ConfigurationParseError(
            "Antenna reference YAML must contain a mapping at the document root."
        )
    try:
        return AntennaReferenceDocument.model_validate(raw)
    except ValidationError as error:
        raise ConfigurationValidationError(
            "Antenna reference validation failed:\n" + _validation_details(error)
        ) from error


class AntennaReferenceYamlSource:
    """One-shot YAML source; callers decide when a restart/reload occurs."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def load_snapshot(self) -> AntennaReferenceSnapshot:
        return load_antenna_reference_document(self._path).snapshot()
