"""Typed YAML configuration for Rolling Thunder."""

from pathlib import Path
from typing import Any, Self

import yaml
from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from rolling_thunder.value_types import BaseCallsign, MaidenheadGrid


class ConfigurationError(Exception):
    """Base exception for application configuration failures."""


class ConfigurationFileError(ConfigurationError):
    """Raised when a configuration file cannot be read."""


class ConfigurationParseError(ConfigurationError):
    """Raised when a configuration file contains invalid YAML."""


class ConfigurationValidationError(ConfigurationError):
    """Raised when parsed configuration does not satisfy the schema."""


class ConfigurationModel(BaseModel):
    """Base model shared by all configuration sections."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class OperatorConfig(ConfigurationModel):
    """Amateur-radio operator settings."""

    callsign: BaseCallsign
    home_grid: MaidenheadGrid


class HardwareConfig(ConfigurationModel):
    """Hardware selection and mock-mode settings."""

    mock: bool = True
    radio_device: Path | None = None
    gps_device: Path | None = None

    @model_validator(mode="after")
    def validate_real_hardware_devices(self) -> Self:
        """Require device preferences when real hardware mode is selected."""
        if self.mock:
            return self

        missing: list[str] = []

        if self.radio_device is None:
            missing.append("hardware.radio_device")

        if self.gps_device is None:
            missing.append("hardware.gps_device")

        if missing:
            missing_fields = ", ".join(missing)
            raise ValueError(
                f"{missing_fields} must be configured when hardware.mock is false"
            )

        return self


class ForgeConfig(ConfigurationModel):
    """Optional Forge service settings."""

    api_url: AnyHttpUrl | None = None


class ContactBackupConfig(ConfigurationModel):
    """Verified local contact-backup settings."""

    enabled: bool = False
    directory: Path = Path("backups/contacts")
    retention_count: int = Field(default=10, ge=1)

    @field_validator("directory", mode="before")
    @classmethod
    def validate_directory(cls, value: object) -> object:
        """Reject empty or current-directory backup paths."""
        if isinstance(value, str) and not value.strip():
            raise ValueError(
                "contact backup directory must not be empty"
            )

        if isinstance(value, Path) and str(value) in {"", "."}:
            raise ValueError(
                "contact backup directory must name a directory"
            )

        if isinstance(value, str) and str(Path(value)) == ".":
            raise ValueError(
                "contact backup directory must name a directory"
            )

        return value


class StorageConfig(ConfigurationModel):
    """Local persistent-storage settings."""

    database_path: Path = Path("data/rolling-thunder.db")
    contact_backups: ContactBackupConfig = ContactBackupConfig()


class ApplicationConfig(ConfigurationModel):
    """Complete Rolling Thunder application configuration."""

    operator: OperatorConfig
    hardware: HardwareConfig = HardwareConfig()
    forge: ForgeConfig = ForgeConfig()
    storage: StorageConfig = StorageConfig()


def resolve_contact_backup_directory(
    config: ApplicationConfig,
    config_path: Path,
) -> Path:
    """Resolve the configured backup directory relative to the YAML file."""
    directory = config.storage.contact_backups.directory

    if directory.is_absolute():
        return directory

    return (config_path.parent / directory).resolve()


def _format_validation_error(error: ValidationError) -> str:
    """Convert Pydantic validation details into actionable configuration paths."""
    messages: list[str] = []

    for item in error.errors(include_url=False):
        location = ".".join(str(part) for part in item["loc"]) or "<configuration>"
        messages.append(f"- {location}: {item['msg']}")

    return "\n".join(messages)


def load_config(path: Path) -> ApplicationConfig:
    """Load and validate an application configuration from a YAML file."""
    try:
        yaml_text = path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise ConfigurationFileError(
            f"Configuration file was not found: {path}. "
            "Copy config/rolling-thunder.example.yaml to "
            "config/rolling-thunder.yaml and update it for this machine."
        ) from error
    except OSError as error:
        raise ConfigurationFileError(
            f"Configuration file could not be read: {path}: {error}"
        ) from error

    try:
        raw_config: Any = yaml.safe_load(yaml_text)
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)

        if mark is not None:
            location = f"line {mark.line + 1}, column {mark.column + 1}"
        else:
            location = "an unknown location"

        problem = getattr(error, "problem", None) or str(error)

        raise ConfigurationParseError(
            f"Configuration YAML is invalid at {location}: {problem}"
        ) from error

    if not isinstance(raw_config, dict):
        raise ConfigurationParseError(
            "Configuration YAML must contain a mapping at the document root."
        )

    try:
        return ApplicationConfig.model_validate(raw_config)
    except ValidationError as error:
        details = _format_validation_error(error)
        raise ConfigurationValidationError(
            f"Configuration validation failed:\n{details}"
        ) from error
