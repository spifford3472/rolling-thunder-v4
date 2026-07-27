"""Typed YAML configuration for Rolling Thunder."""

from enum import StrEnum
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

from rolling_thunder.physical_controls import ControlAction
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
                raise ValueError("must be an absolute device path, such as /dev/ttyUSB0")

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
            raise ValueError(f"{missing_fields} must be configured when hardware.mock is false")

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


class HomePlatformConfig(ConfigurationModel):
    """Optional Home Station Platform connectivity and polling settings."""

    enabled: bool = False
    base_url: AnyHttpUrl | None = None
    request_timeout_s: float = Field(default=5.0, gt=0, le=60)
    health_poll_interval_s: float = Field(default=30.0, gt=0, le=3_600)
    contact_sync_interval_s: float = Field(default=30.0, gt=0, le=3_600)
    contact_sync_batch_size: int = Field(default=25, ge=1, le=1_000)

    @model_validator(mode="after")
    def validate_enabled_platform(self) -> Self:
        """Require a base URL whenever Home Station Platform access is enabled."""
        if self.enabled and self.base_url is None:
            raise ValueError(
                "home_platform.base_url must be configured when home_platform.enabled is true"
            )
        return self


class NetworkKeepaliveConfig(ConfigurationModel):
    """Optional cellular/WAN keepalive settings."""

    enabled: bool = False
    target_url: AnyHttpUrl | None = None
    interval_s: float = Field(default=30.0, gt=0, le=3_600)
    timeout_s: float = Field(default=5.0, gt=0, le=60)

    @model_validator(mode="after")
    def validate_enabled_keepalive(self) -> Self:
        """Require a target URL whenever keepalive traffic is enabled."""
        if self.enabled and self.target_url is None:
            raise ValueError(
                "network_keepalive.target_url must be configured when "
                "network_keepalive.enabled is true"
            )
        return self


class PotaSpotsConfig(ConfigurationModel):
    """Optional POTA spot retrieval and polling settings."""

    enabled: bool = False
    base_url: AnyHttpUrl = AnyHttpUrl("https://api.pota.app")
    request_timeout_s: float = Field(default=5.0, gt=0, le=60)
    refresh_interval_s: float = Field(default=60.0, gt=0, le=3_600)
    refresh_on_start: bool = True


class PhysicalControlTransport(StrEnum):
    """Supported physical-control input transports."""

    MOCK = "mock"
    SERIAL = "serial"


class PhysicalControlsConfig(ConfigurationModel):
    """Physical-control transport, mappings, and input safeguards."""

    enabled: bool = False
    transport: PhysicalControlTransport = PhysicalControlTransport.MOCK
    device: Path | None = None
    baud_rate: int = Field(default=115_200, ge=1, le=4_000_000)
    maximum_line_bytes: int = Field(default=256, ge=32, le=4_096)
    maximum_read_bytes: int = Field(default=4_096, ge=1, le=65_536)
    maximum_events_per_drain: int = Field(default=32, ge=1, le=1_024)
    repeat_suppression_s: float = Field(default=0.25, ge=0, le=5)
    mappings: dict[str, ControlAction] = Field(default_factory=dict)

    @field_validator("device", mode="before")
    @classmethod
    def validate_device(cls, value: object) -> object:
        """Require a usable absolute serial-device path when one is supplied."""
        if value is None:
            return value
        if isinstance(value, str) and not value.strip():
            raise ValueError("must not be empty")

        path = Path(value) if isinstance(value, (str, Path)) else value
        if isinstance(path, Path):
            if str(path) in {"", "."}:
                raise ValueError("must name a serial device")
            if not path.is_absolute():
                raise ValueError("must be an absolute device path, such as /dev/ttyACM0")
        return path

    @field_validator("mappings")
    @classmethod
    def validate_mappings(
        cls,
        value: dict[str, ControlAction],
    ) -> dict[str, ControlAction]:
        """Normalize opaque input identifiers and reject ambiguous mappings."""
        normalized: dict[str, ControlAction] = {}
        for raw_input_id, action in value.items():
            input_id = raw_input_id.strip()
            if not input_id:
                raise ValueError("input identifiers must not be blank")
            if input_id in normalized:
                raise ValueError(f"duplicate mapping for input identifier {input_id!r}")
            normalized[input_id] = action
        return normalized

    @model_validator(mode="after")
    def validate_transport_requirements(self) -> Self:
        """Require a serial device only when the serial transport is enabled."""
        if (
            self.enabled
            and self.transport is PhysicalControlTransport.SERIAL
            and self.device is None
        ):
            raise ValueError(
                "physical_controls.device must be configured when "
                "physical_controls transport is serial"
            )
        return self


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
    home_platform: HomePlatformConfig = HomePlatformConfig()
    network_keepalive: NetworkKeepaliveConfig = NetworkKeepaliveConfig()
    pota_spots: PotaSpotsConfig = PotaSpotsConfig()
    physical_controls: PhysicalControlsConfig = PhysicalControlsConfig()
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
    return config.model_copy(update={"storage": resolved_storage, "speech": resolved_speech})
