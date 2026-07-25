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

    @field_validator("radio_device", "gps_device", mode="before")
    @classmethod
    def validate_device_path(cls, value: object) -> object:
        """Require configured hardware devices to use usable absolute paths."""
        if value is None:
            return value

        if isinstance(value, str) and not value.strip():
            raise ValueError("must not be empty")

        path = Path(value) if isinstance(value, (str, Path)) else value

        if isinstance(path, Path):
            if str(path) in {"", "."}:
                raise ValueError("must name a device path")
            if not path.is_absolute():
                raise ValueError(
                    "must be an absolute device path, such as /dev/ttyUSB0"
                )

        return path

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


class SpeechConfig(ConfigurationModel):
    """Offline push-to-listen speech-recognition settings."""

    enabled: bool = False
    audio_device: str = "default"
    model_path: Path | None = None
    capture_duration_seconds: int = Field(default=8, ge=1, le=30)
    sample_rate: int = Field(default=16_000, ge=8_000, le=48_000)

    @field_validator("audio_device")
    @classmethod
    def validate_audio_device(cls, value: str) -> str:
        """Require a nonblank ALSA device selector."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be empty")
        return normalized

    @field_validator("model_path", mode="before")
    @classmethod
    def validate_model_path(cls, value: object) -> object:
        """Reject empty or current-directory model paths."""
        if value is None:
            return value
        if isinstance(value, str) and not value.strip():
            raise ValueError("must not be empty")
        if isinstance(value, (str, Path)) and str(Path(value)) == ".":
            raise ValueError("must name a Vosk model directory")
        return value

    @model_validator(mode="after")
    def validate_enabled_speech(self) -> Self:
        """Require a model path whenever live recognition is enabled."""
        if self.enabled and self.model_path is None:
            raise ValueError("speech.model_path must be configured when speech.enabled is true")
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
            raise ValueError("contact backup directory must not be empty")

        if isinstance(value, Path) and str(value) in {"", "."}:
            raise ValueError("contact backup directory must name a directory")

        if isinstance(value, str) and str(Path(value)) == ".":
            raise ValueError("contact backup directory must name a directory")

        return value


class StorageConfig(ConfigurationModel):
    """Local persistent-storage settings."""

    database_path: Path = Path("data/rolling-thunder.db")
    contact_backups: ContactBackupConfig = ContactBackupConfig()

    @field_validator("database_path", mode="before")
    @classmethod
    def validate_database_path(cls, value: object) -> object:
        """Reject empty paths and paths that only name the current directory."""
        if isinstance(value, str) and not value.strip():
            raise ValueError("database path must not be empty")

        if isinstance(value, (str, Path)) and str(Path(value)) == ".":
            raise ValueError("database path must name a database file")

        return value


class ApplicationConfig(ConfigurationModel):
    """Complete Rolling Thunder application configuration."""

    operator: OperatorConfig
    hardware: HardwareConfig = HardwareConfig()
    speech: SpeechConfig = SpeechConfig()
    forge: ForgeConfig = ForgeConfig()
    storage: StorageConfig = StorageConfig()


def resolve_database_path(
    config: ApplicationConfig,
    config_path: Path,
) -> Path:
    """Resolve the configured database path relative to the YAML file."""
    database_path = config.storage.database_path

    if database_path.is_absolute():
        return database_path

    return (config_path.parent / database_path).resolve()


def resolve_contact_backup_directory(
    config: ApplicationConfig,
    config_path: Path,
) -> Path:
    """Resolve the configured backup directory relative to the YAML file."""
    directory = config.storage.contact_backups.directory

    if directory.is_absolute():
        return directory

    return (config_path.parent / directory).resolve()


def resolve_speech_model_path(
    config: ApplicationConfig,
    config_path: Path,
) -> Path | None:
    """Resolve the optional Vosk model path relative to the YAML file."""
    model_path = config.speech.model_path
    if model_path is None or model_path.is_absolute():
        return model_path
    return (config_path.parent / model_path).resolve()


def _format_validation_error(error: ValidationError) -> str:
    """Convert Pydantic validation details into actionable configuration paths."""
    messages: list[str] = []

    for item in error.errors(include_url=False):
        location = ".".join(str(part) for part in item["loc"]) or "<configuration>"
        messages.append(f"- {location}: {item['msg']}")

    return "\n".join(messages)


def load_config(path: Path) -> ApplicationConfig:
    """Load, validate, and resolve an application configuration YAML file."""
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
        config = ApplicationConfig.model_validate(raw_config)
    except ValidationError as error:
        details = _format_validation_error(error)
        raise ConfigurationValidationError(
            f"Configuration validation failed:\n{details}"
        ) from error

    resolved_storage = config.storage.model_copy(
        update={"database_path": resolve_database_path(config, path)}
    )
    resolved_speech = config.speech.model_copy(
        update={"model_path": resolve_speech_model_path(config, path)}
    )
    return config.model_copy(
        update={"storage": resolved_storage, "speech": resolved_speech}
    )
