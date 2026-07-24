"""Typed YAML configuration for Rolling Thunder."""

import re
from pathlib import Path
from typing import Any, Self

import yaml
from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    ValidationError,
    field_validator,
    model_validator,
)

_CALLSIGN_PATTERN = re.compile(r"^[A-Z0-9]{1,3}[0-9][A-Z0-9]{1,4}$")
_GRID_PATTERN = re.compile(
    r"^[A-R]{2}[0-9]{2}(?:[A-X]{2}(?:[0-9]{2})?)?$",
    re.IGNORECASE,
)


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

    callsign: str
    home_grid: str

    @field_validator("callsign")
    @classmethod
    def validate_callsign(cls, value: str) -> str:
        """Normalize and validate an amateur-radio callsign."""
        normalized = value.strip().upper()

        if not _CALLSIGN_PATTERN.fullmatch(normalized):
            raise ValueError(
                "must be a valid amateur-radio callsign, such as KI5VNB"
            )

        return normalized

    @field_validator("home_grid")
    @classmethod
    def validate_home_grid(cls, value: str) -> str:
        """Normalize and validate a Maidenhead grid locator."""
        normalized = value.strip()

        if not _GRID_PATTERN.fullmatch(normalized):
            raise ValueError(
                "must be a 4-, 6-, or 8-character Maidenhead grid, such as EM79xm"
            )

        if len(normalized) == 4:
            return normalized[:2].upper() + normalized[2:]

        return (
            normalized[:2].upper()
            + normalized[2:4]
            + normalized[4:6].lower()
            + normalized[6:]
        )


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


class StorageConfig(ConfigurationModel):
    """Local persistent-storage settings."""

    database_path: Path = Path("data/rolling-thunder.db")


class ApplicationConfig(ConfigurationModel):
    """Complete Rolling Thunder application configuration."""

    operator: OperatorConfig
    hardware: HardwareConfig = HardwareConfig()
    forge: ForgeConfig = ForgeConfig()
    storage: StorageConfig = StorageConfig()


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
