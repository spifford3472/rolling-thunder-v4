"""Typed configuration for the independent Forge completed-QSO worker."""

from pathlib import Path
from typing import Any, Self

import yaml
from pydantic import AnyHttpUrl, Field, ValidationError, field_validator, model_validator

from rolling_thunder.config import ConfigurationModel


class ForgePropagationQsoWorkerConfigurationError(ValueError):
    """Raised when completed-QSO worker configuration cannot be loaded safely."""


class ForgePropagationQsoWorkerConfig(ConfigurationModel):
    """Non-secret, disabled-by-default configuration for one worker identity."""

    enabled: bool = False
    voacap_enabled: bool = False
    worker_identity: str = Field(
        default="forge-propagation-qso-worker",
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    inbox_database_path: Path = Path("data/forge-propagation-qso-inbox.db")
    history_database_path: Path = Path("data/forge-propagation-history.db")
    status_path: Path = Path("data/forge-propagation-qso-worker-status.json")
    poll_interval_s: float = Field(default=30.0, ge=1.0, le=3600.0)
    batch_limit: int = Field(default=20, ge=1, le=100)
    lease_duration_s: int = Field(default=300, ge=10, le=3600)
    max_attempts: int = Field(default=5, ge=1, le=100)
    retry_base_s: int = Field(default=60, ge=1, le=86_400)
    retry_max_s: int = Field(default=3600, ge=1, le=604_800)
    provider_timeout_s: float = Field(default=10.0, gt=0, le=60)
    voacap_base_url: AnyHttpUrl = AnyHttpUrl("http://127.0.0.1:8787")

    @field_validator("worker_identity", mode="before")
    @classmethod
    def normalize_worker_identity(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator(
        "inbox_database_path", "history_database_path", "status_path", mode="before"
    )
    @classmethod
    def validate_file_path(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            raise ValueError("must not be empty")
        if isinstance(value, (str, Path)) and str(Path(value)) == ".":
            raise ValueError("must name a file")
        return value

    @model_validator(mode="after")
    def validate_worker_bounds(self) -> Self:
        if self.retry_max_s < self.retry_base_s:
            raise ValueError("retry_max_s must be at least retry_base_s")
        if self.lease_duration_s <= self.provider_timeout_s * 2:
            raise ValueError("lease_duration_s must exceed two provider timeouts")
        if len(
            {self.inbox_database_path, self.history_database_path, self.status_path}
        ) != 3:
            raise ValueError("inbox, history, and status paths must differ")
        return self


def load_forge_propagation_qso_worker_config(
    path: Path,
) -> ForgePropagationQsoWorkerConfig:
    """Load one worker config and resolve its owned paths relative to the file."""
    try:
        raw_text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ForgePropagationQsoWorkerConfigurationError(
            f"cannot read completed-QSO worker config: {path}"
        ) from error
    try:
        raw: Any = yaml.safe_load(raw_text)
    except yaml.YAMLError as error:
        raise ForgePropagationQsoWorkerConfigurationError(
            "invalid completed-QSO worker YAML"
        ) from error
    if not isinstance(raw, dict):
        raise ForgePropagationQsoWorkerConfigurationError(
            "completed-QSO worker configuration root must be a mapping"
        )
    try:
        config = ForgePropagationQsoWorkerConfig.model_validate(raw)
    except ValidationError as error:
        details = "; ".join(
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
            for item in error.errors(include_url=False)
        )
        raise ForgePropagationQsoWorkerConfigurationError(
            f"invalid completed-QSO worker configuration: {details}"
        ) from error

    def resolved(candidate: Path) -> Path:
        return candidate if candidate.is_absolute() else (path.parent / candidate).resolve()

    inbox_database_path = resolved(config.inbox_database_path)
    history_database_path = resolved(config.history_database_path)
    status_path = resolved(config.status_path)
    if len({inbox_database_path, history_database_path, status_path}) != 3:
        raise ForgePropagationQsoWorkerConfigurationError(
            "inbox, history, and status paths must differ"
        )
    return config.model_copy(
        update={
            "inbox_database_path": inbox_database_path,
            "history_database_path": history_database_path,
            "status_path": status_path,
        }
    )
