"""Immutable offline antenna-reference and RF-exposure domain models."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from rolling_thunder.domain import DomainModel, Frequency


class GainUnit(StrEnum):
    """Supported antenna-gain reference units."""

    DBI = "dBi"
    DBD = "dBd"


class FrequencyRegion(StrEnum):
    """Broad RF region used to prevent treating six metres as HF."""

    HF = "HF"
    VHF = "VHF"
    UHF = "UHF"
    OTHER = "other"


class GroundReflectionModel(StrEnum):
    """Explicit plane-wave reflection assumptions supported by calculator v1."""

    FREE_SPACE = "free_space"
    ARRL_TYPICAL_GROUND = "arrl_typical_ground"

    @property
    def power_density_factor(self) -> float:
        """Return the model's multiplicative power-density factor."""
        if self is GroundReflectionModel.ARRL_TYPICAL_GROUND:
            return 2.56
        return 1.0


class TextProvenance(DomainModel):
    """Human-reviewable source for a catalog value or assumption."""

    source: str = Field(min_length=1, max_length=500)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("source", "notes")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("provenance text must not be blank")
        return normalized


class FrequencySegment(DomainModel):
    """Inclusive frequency segment; values never interpolate beyond this range."""

    lower: Frequency
    upper: Frequency

    @model_validator(mode="after")
    def validate_order(self) -> FrequencySegment:
        if self.lower.hz > self.upper.hz:
            raise ValueError("frequency segment lower bound must not exceed upper bound")
        return self

    def contains(self, frequency: Frequency) -> bool:
        return self.lower.hz <= frequency.hz <= self.upper.hz


class BandAssociation(DomainModel):
    """One explicitly supported antenna band/frequency association."""

    association_id: UUID = Field(default_factory=uuid4)
    label: str = Field(min_length=1, max_length=40)
    region: FrequencyRegion
    frequencies: FrequencySegment
    provenance: TextProvenance

    @field_validator("label")
    @classmethod
    def normalize_label(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("band label must not be blank")
        return normalized

    @model_validator(mode="after")
    def distinguish_six_metres(self) -> BandAssociation:
        if (
            self.label.casefold().replace(" ", "") in {"6m", "6meter", "6metre"}
            and self.region is not FrequencyRegion.VHF
        ):
            raise ValueError("the 6 m band must be classified as VHF, not HF")
        return self


class GainSegment(DomainModel):
    """One sourced gain value valid only inside an explicit frequency segment."""

    gain_id: UUID = Field(default_factory=uuid4)
    frequencies: FrequencySegment
    gain_db: float = Field(allow_inf_nan=False)
    unit: GainUnit
    provenance: TextProvenance

    @property
    def gain_dbi(self) -> float:
        """Return gain relative to isotropic, using the defined 2.15 dB conversion."""
        if self.unit is GainUnit.DBD:
            return self.gain_db + 2.15
        return self.gain_db


class AntennaCatalogEntry(DomainModel):
    """Reference antenna definition, separate from any physical installation."""

    antenna_id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=200)
    manufacturer: str | None = Field(default=None, max_length=200)
    model: str | None = Field(default=None, max_length=200)
    provenance: TextProvenance
    bands: tuple[BandAssociation, ...] = ()
    gains: tuple[GainSegment, ...] = ()
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("name", "manufacturer", "model", "notes")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("antenna text must not be blank")
        return normalized

    @model_validator(mode="after")
    def validate_unique_children(self) -> AntennaCatalogEntry:
        band_ids = [item.association_id for item in self.bands]
        gain_ids = [item.gain_id for item in self.gains]
        if len(band_ids) != len(set(band_ids)):
            raise ValueError("antenna band-association UUIDs must be unique")
        if len(gain_ids) != len(set(gain_ids)):
            raise ValueError("antenna gain UUIDs must be unique")
        return self


class LossSegment(DomainModel):
    """One installation loss contribution, which may explicitly remain unknown."""

    loss_id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=200)
    frequencies: FrequencySegment
    loss_db: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    provenance: TextProvenance

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("loss name must not be blank")
        return normalized


class InstallationBandAssignment(DomainModel):
    """Installation-specific activation of one catalog band association."""

    assignment_id: UUID = Field(default_factory=uuid4)
    association_id: UUID
    active: bool = True
    provenance: TextProvenance


class AntennaInstallation(DomainModel):
    """A physical antenna installation and its independently sourced losses."""

    installation_id: UUID = Field(default_factory=uuid4)
    antenna_id: UUID
    name: str = Field(min_length=1, max_length=200)
    location_description: str = Field(min_length=1, max_length=500)
    losses_complete: bool = False
    loss_segments: tuple[LossSegment, ...] = ()
    band_assignments: tuple[InstallationBandAssignment, ...] = ()
    provenance: TextProvenance
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("name", "location_description", "notes")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("installation text must not be blank")
        return normalized

    @model_validator(mode="after")
    def validate_unique_children(self) -> AntennaInstallation:
        loss_ids = [item.loss_id for item in self.loss_segments]
        assignment_ids = [item.assignment_id for item in self.band_assignments]
        associations = [item.association_id for item in self.band_assignments]
        if len(loss_ids) != len(set(loss_ids)):
            raise ValueError("installation loss UUIDs must be unique")
        if len(assignment_ids) != len(set(assignment_ids)):
            raise ValueError("installation assignment UUIDs must be unique")
        if len(associations) != len(set(associations)):
            raise ValueError("a band association may be assigned only once per installation")
        return self


class ModeProfile(DomainModel):
    """Versionable mode RF-envelope duty factor, independent of transmit fraction."""

    mode_profile_id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=100)
    rf_envelope_duty: float = Field(gt=0, le=1, allow_inf_nan=False)
    provenance: TextProvenance

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("mode profile name must not be blank")
        return normalized


class ExposureScenario(DomainModel):
    """One offline what-if scenario; it has no radio-control authority."""

    scenario_id: UUID = Field(default_factory=uuid4)
    installation_id: UUID
    mode_profile_id: UUID
    name: str = Field(min_length=1, max_length=200)
    frequency: Frequency
    forward_tx_watts: float = Field(gt=0, allow_inf_nan=False)
    controlled_tx_fraction: float = Field(gt=0, le=1, allow_inf_nan=False)
    uncontrolled_tx_fraction: float = Field(gt=0, le=1, allow_inf_nan=False)
    occupant_distance_m: float = Field(default=1.8288, gt=0, allow_inf_nan=False)
    occupant_distance_verified: bool = False
    ground_reflection_model: GroundReflectionModel = GroundReflectionModel.ARRL_TYPICAL_GROUND
    provenance: TextProvenance
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("name", "notes")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("scenario text must not be blank")
        return normalized

    @model_validator(mode="after")
    def validate_mpe_frequency_range(self) -> ExposureScenario:
        if not 300_000 <= self.frequency.hz <= 100_000_000_000:
            raise ValueError("scenario frequency must be within the FCC MPE table range")
        return self


def standard_mode_profiles() -> tuple[ModeProfile, ...]:
    """Return sourced v1 reference profiles without writing user storage."""
    source = TextProvenance(
        source="ARRL RF Exposure Calculator instructions, retrieved 2026-10-12"
    )
    return (
        ModeProfile(
            mode_profile_id=UUID("231e36a4-5e67-5dd4-bd42-6e8052aab8f8"),
            name="FT8",
            rf_envelope_duty=1.0,
            provenance=source,
        ),
        ModeProfile(
            mode_profile_id=UUID("8f251203-8bdd-54ef-bca3-3b835f16ec6c"),
            name="SSB unprocessed",
            rf_envelope_duty=0.20,
            provenance=source,
        ),
        ModeProfile(
            mode_profile_id=UUID("215201f4-06ee-5275-a78f-9c94bf59052d"),
            name="SSB heavily processed",
            rf_envelope_duty=0.50,
            provenance=source,
        ),
        ModeProfile(
            mode_profile_id=UUID("07a258a9-4058-50f1-a6e0-250b25a94033"),
            name="6 m FM",
            rf_envelope_duty=1.0,
            provenance=source,
        ),
    )
