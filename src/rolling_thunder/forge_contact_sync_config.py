"""Typed configuration for the independent Forge Wavelog synchronization service."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, ValidationError, field_validator


class ForgeContactSyncConfigurationError(Exception):
    """Raised when the Forge contact-sync configuration cannot be loaded safely."""


class ForgeContactSyncConfigModel(BaseModel):
    """Frozen base model for contact synchronization configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ForgeContactServerConfig(ForgeContactSyncConfigModel):
    """Private HTTP listener settings."""

    bind_host: str = Field(default="127.0.0.1", min_length=1, max_length=255)
    bind_port: int = Field(default=8767, ge=1, le=65_535)

    @field_validator("bind_host")
    @classmethod
    def normalize_bind_host(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized


class ForgeContactStorageConfig(ForgeContactSyncConfigModel):
    """Durable Forge idempotency-ledger settings."""

    database_path: Path = Path("data/forge-contact-sync.db")

    @field_validator("database_path", mode="before")
    @classmethod
    def validate_database_path(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            raise ValueError("must not be empty")
        if isinstance(value, (str, Path)) and str(Path(value)) == ".":
            raise ValueError("must name a database file")
        return value


class WavelogSyncConfig(ForgeContactSyncConfigModel):
    """Non-secret Wavelog endpoint and hard target identity."""

    base_url: AnyHttpUrl = AnyHttpUrl("http://127.0.0.1:8086")
    station_logbook_name: str = Field(default="KI5VNB Main", min_length=1, max_length=255)
    station_location_name: str = Field(default="Mobile", min_length=1, max_length=255)
    request_timeout_s: float = Field(default=5.0, gt=0, le=60)

    @field_validator("station_logbook_name", "station_location_name")
    @classmethod
    def normalize_target_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("must not be blank")
        return normalized


class ContactWeatherConfig(ForgeContactSyncConfigModel):
    """Bounded Forge-side QSO weather-enrichment settings."""

    enabled: bool = True
    request_timeout_s: float = Field(default=5.0, gt=0, le=30)
    endpoint: AnyHttpUrl = AnyHttpUrl("https://api.open-meteo.com/v1/forecast")


class ForgeContactSyncConfig(ForgeContactSyncConfigModel):
    """Complete Forge contact synchronization process configuration."""

    server: ForgeContactServerConfig = ForgeContactServerConfig()
    storage: ForgeContactStorageConfig = ForgeContactStorageConfig()
    wavelog: WavelogSyncConfig = WavelogSyncConfig()
    weather: ContactWeatherConfig = ContactWeatherConfig()


def load_forge_contact_sync_config(path: Path) -> ForgeContactSyncConfig:
    """Load one YAML file and resolve its ledger path relative to that file."""
    try:
        raw_text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ForgeContactSyncConfigurationError(
            f"Forge contact-sync configuration could not be read: {path}: {error}"
        ) from error
    try:
        raw: Any = yaml.safe_load(raw_text)
    except yaml.YAMLError as error:
        raise ForgeContactSyncConfigurationError(
            f"Forge contact-sync configuration contains invalid YAML: {path}: {error}"
        ) from error
    if not isinstance(raw, dict):
        raise ForgeContactSyncConfigurationError(
            "Forge contact-sync configuration root must be a mapping."
        )
    try:
        config = ForgeContactSyncConfig.model_validate(raw)
    except ValidationError as error:
        details = "; ".join(
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
            for item in error.errors(include_url=False)
        )
        raise ForgeContactSyncConfigurationError(
            f"Forge contact-sync configuration validation failed: {details}"
        ) from error

    database_path = config.storage.database_path
    if not database_path.is_absolute():
        database_path = (path.parent / database_path).resolve()
    return config.model_copy(
        update={
            "storage": config.storage.model_copy(update={"database_path": database_path})
        }
    )
