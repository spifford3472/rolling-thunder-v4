"""Structured FT8 attempt telemetry for future machine analysis."""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field, field_serializer, field_validator, model_validator

from rolling_thunder.domain import DomainModel
from rolling_thunder.value_types import Callsign, MaidenheadGrid


class FT8PerformanceUploadDisposition(StrEnum):
    """Idempotent Forge persistence result."""

    ACCEPTED = "accepted"
    ALREADY_EXISTS = "already_exists"


class FT8AttemptOutcome(StrEnum):
    """Terminal outcomes stored independently from normal QSO contacts."""

    COMPLETED = "completed"
    ABORTED = "aborted"
    RETRY_EXHAUSTED = "retry_exhausted"
    ERROR = "error"
    PREPARATION_FAILED = "preparation_failed"


class FT8AttemptSeed(DomainModel):
    """Frozen operator-selection metadata established before radio preparation."""

    attempt_id: UUID
    callsign: Callsign
    started_at_utc: datetime
    band: str | None = Field(default=None, max_length=16)
    dial_frequency_hz: int | None = Field(default=None, gt=0, le=300_000_000_000)
    local_grid: MaidenheadGrid | None = None
    remote_grid: MaidenheadGrid | None = None
    audio_frequency_hz: int = Field(gt=0)
    selected_snr_db: int = Field(ge=-50, le=49)
    pota_cq: bool = False

    @field_validator("started_at_utc")
    @classmethod
    def normalize_started_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("must be timezone-aware")
        return value.astimezone(UTC)

    @field_serializer("started_at_utc")
    def serialize_started_at(self, value: datetime) -> str:
        return value.isoformat().replace("+00:00", "Z")


class FT8PerformanceAttempt(DomainModel):
    """One immutable terminal FT8 attempt record."""

    attempt_id: UUID
    callsign: Callsign
    outcome: FT8AttemptOutcome
    success: bool
    terminal_state: str = Field(min_length=1, max_length=64)
    terminal_reason: str | None = Field(default=None, max_length=1000)

    started_at_utc: datetime
    ended_at_utc: datetime
    utc_date: date

    band: str | None = Field(default=None, max_length=16)
    dial_frequency_hz: int | None = Field(default=None, gt=0, le=300_000_000_000)
    mode: str = Field(default="FT8", pattern=r"^FT8$")
    tx_power_target_watts: int = Field(default=20, ge=1, le=100)

    power_meter_raw: int | None = Field(default=None, ge=0, le=255)
    swr_meter_raw: int | None = Field(default=None, ge=0, le=255)
    alc_meter_raw: int | None = Field(default=None, ge=0, le=255)

    sent_report_db: int | None = Field(default=None, ge=-50, le=49)
    received_report_db: int | None = Field(default=None, ge=-50, le=49)
    local_grid: MaidenheadGrid | None = None
    remote_grid: MaidenheadGrid | None = None
    distance_km: float | None = Field(default=None, ge=0)
    audio_frequency_hz: int | None = Field(default=None, gt=0)
    pota_cq: bool = False

    attempt_count: int = Field(default=0, ge=0)
    last_qso_state: str | None = Field(default=None, max_length=64)

    # Reserved, nullable extension points for future propagation correlation.
    voacap_probability: float | None = Field(default=None, ge=0, le=1)
    voacap_predicted_snr_db: float | None = None
    voacap_path: str | None = Field(default=None, max_length=64)
    analysis_schema_version: int = Field(default=1, ge=1)

    @field_validator("started_at_utc", "ended_at_utc")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("must be timezone-aware")
        return value.astimezone(UTC)

    @field_validator("terminal_state", "last_qso_state", "terminal_reason", "voacap_path")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_consistency(self) -> FT8PerformanceAttempt:
        if self.ended_at_utc < self.started_at_utc:
            raise ValueError("ended_at_utc cannot precede started_at_utc")
        if self.utc_date != self.started_at_utc.date():
            raise ValueError("utc_date must match started_at_utc UTC date")
        if self.success != (self.outcome is FT8AttemptOutcome.COMPLETED):
            raise ValueError("success must be true only for completed attempts")
        if self.outcome is not FT8AttemptOutcome.COMPLETED and self.terminal_reason is None:
            raise ValueError("non-completed attempts require terminal_reason")
        return self

    @field_serializer("started_at_utc", "ended_at_utc")
    def serialize_time(self, value: datetime) -> str:
        return value.isoformat().replace("+00:00", "Z")

    @field_serializer("utc_date")
    def serialize_date(self, value: date) -> str:
        return value.isoformat()


class FT8PerformanceUploadResult(DomainModel):
    """Typed acknowledgement from Forge performance persistence."""

    attempt_id: UUID
    disposition: FT8PerformanceUploadDisposition
    received_at_utc: datetime

    @field_validator("received_at_utc")
    @classmethod
    def normalize_received_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("must be timezone-aware")
        return value.astimezone(UTC)

    @field_serializer("received_at_utc")
    def serialize_received_at(self, value: datetime) -> str:
        return value.isoformat().replace("+00:00", "Z")
