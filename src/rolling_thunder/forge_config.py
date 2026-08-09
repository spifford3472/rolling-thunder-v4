"""Typed YAML configuration for the independent Forge spot service."""

from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
)

from rolling_thunder.value_types import BaseCallsign


class ForgeConfigurationError(Exception):
    """Base exception for Forge configuration failures."""


class ForgeConfigurationFileError(ForgeConfigurationError):
    """Raised when a Forge configuration file cannot be read."""


class ForgeConfigurationParseError(ForgeConfigurationError):
    """Raised when a Forge configuration file contains invalid YAML."""


class ForgeConfigurationValidationError(ForgeConfigurationError):
    """Raised when parsed Forge configuration does not satisfy the schema."""


class ForgeConfigurationModel(BaseModel):
    """Frozen base model shared by Forge configuration sections."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ForgeLogLevel(StrEnum):
    """Supported Forge process logging levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class ForgeServerConfig(ForgeConfigurationModel):
    """Read-only HTTP server bind settings."""

    bind_host: str = Field(default="127.0.0.1", min_length=1, max_length=255)
    bind_port: int = Field(default=8765, ge=1, le=65_535)

    @field_validator("bind_host")
    @classmethod
    def normalize_bind_host(cls, value: str) -> str:
        """Trim the bind host and reject blank values."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized


class ForgeStorageConfig(ForgeConfigurationModel):
    """Forge-specific durable snapshot storage settings."""

    database_path: Path = Path("data/forge-spots.db")

    @field_validator("database_path", mode="before")
    @classmethod
    def validate_database_path(cls, value: object) -> object:
        """Reject blank paths and paths naming only the current directory."""
        if isinstance(value, str) and not value.strip():
            raise ValueError("must not be empty")
        if isinstance(value, (str, Path)) and str(Path(value)) == ".":
            raise ValueError("must name a database file")
        return value


class ForgeAggregationConfig(ForgeConfigurationModel):
    """Provider refresh lifecycle settings."""

    refresh_interval_s: float = Field(default=60.0, gt=0, le=86_400)
    refresh_on_start: bool = True


class ForgePotaProviderConfig(ForgeConfigurationModel):
    """Public Parks on the Air provider settings."""

    enabled: bool = True
    base_url: AnyHttpUrl = AnyHttpUrl("https://api.pota.app")
    request_timeout_s: float = Field(default=5.0, gt=0, le=60)


class ForgeDxSpiderProviderConfig(ForgeConfigurationModel):
    """Bounded public DXSpider snapshot-session settings."""

    enabled: bool = False
    host: str = Field(
        default="cluster.example.invalid",
        min_length=1,
        max_length=255,
    )
    port: int = Field(default=7300, ge=1, le=65_535)
    login_callsign: BaseCallsign = "N0CALL"
    connect_timeout_s: float = Field(default=5.0, gt=0, le=60)
    read_timeout_s: float = Field(default=5.0, gt=0, le=60)
    max_response_bytes: int = Field(
        default=262_144,
        ge=4_096,
        le=4_194_304,
    )
    max_spots: int = Field(default=250, ge=1, le=5_000)
    max_spot_age_s: float = Field(default=3_600.0, gt=0, le=86_400)

    @field_validator("host")
    @classmethod
    def normalize_host(cls, value: str) -> str:
        """Trim the cluster host and reject blank values."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized


class ForgeQrzEnrichmentConfig(ForgeConfigurationModel):
    """Optional bounded Forge-side QRZ enrichment settings."""

    enabled: bool = False
    request_timeout_s: float = Field(default=5.0, gt=0, le=60)
    minimum_request_interval_s: float = Field(default=1.0, ge=0, le=60)
    max_lookups_per_refresh: int = Field(default=25, ge=1, le=1_000)
    positive_ttl_s: float = Field(default=86_400.0, gt=0, le=31_536_000)
    negative_ttl_s: float = Field(default=3_600.0, gt=0, le=604_800)
    max_cache_entries: int = Field(default=2_000, ge=1, le=100_000)


class ForgeWeatherConfig(ForgeConfigurationModel):
    """Retained Forge weather provider and deterministic refresh settings."""

    enabled: bool = False
    endpoint: AnyHttpUrl = AnyHttpUrl("https://api.open-meteo.com/v1/forecast")
    request_timeout_s: float = Field(default=5.0, gt=0, le=60)
    check_interval_s: float = Field(default=60.0, gt=0, le=3_600)
    max_forecast_age_s: float = Field(default=1_800.0, gt=0, le=86_400)
    movement_refresh_km: float = Field(default=10.0, gt=0, le=1_000)
    refresh_on_start: bool = True


class ForgeRadarConfig(ForgeConfigurationModel):
    """Optional NOAA/NWS radar discovery and bounded tile-cache settings."""

    enabled: bool = False
    endpoint: AnyHttpUrl = AnyHttpUrl(
        "https://mapservices.weather.noaa.gov/eventdriven/rest/services/"
        "radar/radar_base_reflectivity_time/ImageServer"
    )
    request_timeout_s: float = Field(default=5.0, gt=0, le=60)
    check_interval_s: float = Field(default=60.0, gt=0, le=3_600)
    stale_after_s: float = Field(default=900.0, gt=0, le=86_400)
    hide_after_s: float = Field(default=1_800.0, gt=0, le=86_400)
    maximum_cached_tiles: int = Field(default=256, ge=1, le=4_096)
    refresh_on_start: bool = True

    @field_validator("hide_after_s")
    @classmethod
    def hide_after_must_exceed_stale_after(
        cls,
        value: float,
        info: Any,
    ) -> float:
        stale_after = info.data.get("stale_after_s")
        if isinstance(stale_after, (int, float)) and value <= stale_after:
            raise ValueError("must exceed stale_after_s")
        return value


class ForgeApplicationConfig(ForgeConfigurationModel):
    """Complete independent Forge spot-service configuration."""

    server: ForgeServerConfig = ForgeServerConfig()
    storage: ForgeStorageConfig = ForgeStorageConfig()
    aggregation: ForgeAggregationConfig = ForgeAggregationConfig()
    pota: ForgePotaProviderConfig = ForgePotaProviderConfig()
    dxspider: ForgeDxSpiderProviderConfig = ForgeDxSpiderProviderConfig()
    qrz: ForgeQrzEnrichmentConfig = ForgeQrzEnrichmentConfig()
    weather: ForgeWeatherConfig = ForgeWeatherConfig()
    radar: ForgeRadarConfig = ForgeRadarConfig()
    logging_level: ForgeLogLevel = ForgeLogLevel.INFO

    @field_validator("logging_level", mode="before")
    @classmethod
    def normalize_logging_level(cls, value: object) -> object:
        """Normalize configured logging-level text."""
        if isinstance(value, str):
            return value.strip().upper()
        return value


def resolve_forge_database_path(
    config: ForgeApplicationConfig,
    config_path: Path,
) -> Path:
    """Resolve the Forge database path relative to its YAML file."""
    database_path = config.storage.database_path
    if database_path.is_absolute():
        return database_path
    return (config_path.parent / database_path).resolve()


def _format_validation_error(error: ValidationError) -> str:
    """Convert Pydantic validation details into actionable dotted paths."""
    messages: list[str] = []
    for item in error.errors(include_url=False):
        location = ".".join(str(part) for part in item["loc"]) or "<configuration>"
        messages.append(f"- {location}: {item['msg']}")
    return "\n".join(messages)


def load_forge_config(path: Path) -> ForgeApplicationConfig:
    """Load, validate, and resolve one Forge YAML configuration file."""
    try:
        yaml_text = path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise ForgeConfigurationFileError(
            f"Forge configuration file was not found: {path}. "
            "Copy config/forge-spots.example.yaml and update it for this machine."
        ) from error
    except OSError as error:
        raise ForgeConfigurationFileError(
            f"Forge configuration file could not be read: {path}: {error}"
        ) from error

    try:
        raw_config: Any = yaml.safe_load(yaml_text)
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        location = (
            f"line {mark.line + 1}, column {mark.column + 1}"
            if mark is not None
            else "an unknown location"
        )
        problem = getattr(error, "problem", None) or str(error)
        raise ForgeConfigurationParseError(
            f"Forge configuration YAML is invalid at {location}: {problem}"
        ) from error

    if not isinstance(raw_config, dict):
        raise ForgeConfigurationParseError(
            "Forge configuration YAML must contain a mapping at the document root."
        )

    try:
        config = ForgeApplicationConfig.model_validate(raw_config)
    except ValidationError as error:
        details = _format_validation_error(error)
        raise ForgeConfigurationValidationError(
            f"Forge configuration validation failed:\n{details}"
        ) from error

    resolved_storage = config.storage.model_copy(
        update={"database_path": resolve_forge_database_path(config, path)}
    )
    return config.model_copy(update={"storage": resolved_storage})
