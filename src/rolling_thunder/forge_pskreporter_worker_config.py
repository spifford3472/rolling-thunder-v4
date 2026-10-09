"""Typed configuration for the independent Forge PSK Reporter worker service."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Self

import yaml
from pydantic import Field, ValidationError, field_validator, model_validator

from rolling_thunder.config import ConfigurationModel
from rolling_thunder.forge_pskreporter import PskReporterConfig

_ENVIRONMENT_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")


class ForgePskReporterWorkerConfigurationError(ValueError):
    """Raised when PSK Reporter worker configuration cannot be loaded safely."""


class ForgePskReporterServerConfig(ConfigurationModel):
    """Private authenticated event-ingestion listener settings."""

    bind_host: str = Field(default="127.0.0.1", min_length=1, max_length=255)
    bind_port: int = Field(default=8789, ge=1, le=65_535)
    maximum_event_bytes: int = Field(default=131_072, ge=4096, le=1_048_576)

    @field_validator("bind_host")
    @classmethod
    def normalize_bind_host(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized


class ForgePskReporterWorkerConfig(ConfigurationModel):
    """Non-secret, independently gated service and provider configuration."""

    enabled: bool = False
    ingestion_enabled: bool = False
    bearer_token_environment: str = "ROLLING_THUNDER_PSKREPORTER_INGEST_TOKEN"
    server: ForgePskReporterServerConfig = ForgePskReporterServerConfig()
    orchestration_database_path: Path = Path("data/forge-pskreporter-orchestration.db")
    history_database_path: Path = Path("data/forge-pskreporter-history.db")
    status_path: Path = Path("data/forge-pskreporter-worker-status.json")
    scheduler_interval_s: float = Field(default=30.0, ge=1.0, le=300.0)
    pskreporter: PskReporterConfig = PskReporterConfig()

    @field_validator("bearer_token_environment")
    @classmethod
    def validate_environment_name(cls, value: str) -> str:
        normalized = value.strip()
        if not _ENVIRONMENT_NAME.fullmatch(normalized):
            raise ValueError("must be an uppercase environment variable name")
        return normalized

    @field_validator(
        "orchestration_database_path", "history_database_path", "status_path", mode="before"
    )
    @classmethod
    def validate_file_path(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            raise ValueError("must not be empty")
        if isinstance(value, (str, Path)) and str(Path(value)) == ".":
            raise ValueError("must name a file")
        return value

    @model_validator(mode="after")
    def validate_isolation(self) -> Self:
        if len(
            {
                self.orchestration_database_path,
                self.history_database_path,
                self.status_path,
            }
        ) != 3:
            raise ValueError("orchestration, history, and status paths must differ")
        return self


def load_forge_pskreporter_worker_config(path: Path) -> ForgePskReporterWorkerConfig:
    """Load YAML and resolve only service-owned files relative to its location."""
    try:
        raw_text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ForgePskReporterWorkerConfigurationError(
            f"cannot read PSK Reporter worker config: {path}"
        ) from error
    try:
        raw: Any = yaml.safe_load(raw_text)
    except yaml.YAMLError as error:
        raise ForgePskReporterWorkerConfigurationError(
            "invalid PSK Reporter worker YAML"
        ) from error
    if not isinstance(raw, dict):
        raise ForgePskReporterWorkerConfigurationError(
            "PSK Reporter worker configuration root must be a mapping"
        )
    try:
        config = ForgePskReporterWorkerConfig.model_validate(raw)
    except ValidationError as error:
        details = "; ".join(
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
            for item in error.errors(include_url=False)
        )
        raise ForgePskReporterWorkerConfigurationError(
            f"invalid PSK Reporter worker configuration: {details}"
        ) from error

    def resolved(candidate: Path) -> Path:
        return candidate if candidate.is_absolute() else (path.parent / candidate).resolve()

    orchestration_path = resolved(config.orchestration_database_path)
    history_path = resolved(config.history_database_path)
    status_path = resolved(config.status_path)
    if len({orchestration_path, history_path, status_path}) != 3:
        raise ForgePskReporterWorkerConfigurationError(
            "orchestration, history, and status paths must differ"
        )
    return config.model_copy(
        update={
            "orchestration_database_path": orchestration_path,
            "history_database_path": history_path,
            "status_path": status_path,
        }
    )
