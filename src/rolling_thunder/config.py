"""Typed YAML configuration for Rolling Thunder."""

from enum import StrEnum
from pathlib import Path
from typing import Any, Self
from urllib.parse import urlparse

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

from rolling_thunder.dmr_dashboard_config import DmrHotspotConfig
from rolling_thunder.map_sources import (
    DEFAULT_MAP_ATTRIBUTION,
    MapPackageStyle,
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


class HardwareAdapterMode(StrEnum):
    """Whether one hardware adapter uses a mock or physical implementation."""

    MOCK = "mock"
    REAL = "real"


class HardwareConfig(ConfigurationModel):
    """Hardware adapter selection and serial-device settings."""

    mock: bool = True
    radio_mode: HardwareAdapterMode | None = None
    gps_mode: HardwareAdapterMode | None = None
    radio_device: Path | None = None
    radio_baud_rate: int = Field(default=38_400, ge=1, le=4_000_000)
    radio_timeout_s: float = Field(default=1.0, gt=0, le=60)
    gps_device: Path | None = None
    gps_baud_rate: int = Field(default=9_600, ge=1, le=4_000_000)
    gps_timeout_s: float = Field(default=2.0, gt=0, le=60)

    @property
    def effective_radio_mode(self) -> HardwareAdapterMode:
        """Resolve explicit radio mode or fall back to legacy global mock mode."""
        if self.radio_mode is not None:
            return self.radio_mode
        return HardwareAdapterMode.MOCK if self.mock else HardwareAdapterMode.REAL

    @property
    def effective_gps_mode(self) -> HardwareAdapterMode:
        """Resolve explicit GPS mode or fall back to legacy global mock mode."""
        if self.gps_mode is not None:
            return self.gps_mode
        return HardwareAdapterMode.MOCK if self.mock else HardwareAdapterMode.REAL

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
        """Require only the devices selected for physical hardware operation."""
        missing: list[str] = []

        if self.effective_radio_mode is HardwareAdapterMode.REAL and self.radio_device is None:
            missing.append("hardware.radio_device")

        if self.effective_gps_mode is HardwareAdapterMode.REAL and self.gps_device is None:
            missing.append("hardware.gps_device")

        if missing:
            missing_fields = ", ".join(missing)
            raise ValueError(
                f"{missing_fields} must be configured when its selected hardware mode is real"
            )

        return self


class SpeechConfig(ConfigurationModel):
    """Offline push-to-listen speech-recognition settings."""

    enabled: bool = False
    audio_device: str = "default"
    model_path: Path | None = None
    capture_duration_seconds: int = Field(default=8, ge=1, le=30)
    sample_rate: int = Field(default=16_000, ge=8_000, le=48_000)
    channels: int = Field(default=1, ge=1, le=8)

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


class ForgeWeatherClientConfig(ConfigurationModel):
    """Optional Pi-side retained-weather polling settings under Forge."""

    enabled: bool = False
    refresh_interval_s: float = Field(default=900.0, gt=0, le=86_400)
    refresh_on_start: bool = True
    stale_after_s: float = Field(default=1_800.0, gt=0, le=172_800)


class ForgeWeatherAlertClientConfig(ConfigurationModel):
    """Location-aware Pi weather-alert polling and GPS freshness settings."""

    enabled: bool = False
    refresh_interval_s: float = Field(
        default=30.0,
        ge=5.0,
        le=3_600.0,
    )
    refresh_on_start: bool = False
    location_publish_interval_s: float = Field(
        default=15.0,
        ge=5.0,
        le=30.0,
    )
    audio_device: str = "default"

    @field_validator("audio_device")
    @classmethod
    def validate_audio_device(
        cls,
        value: str,
    ) -> str:
        """Require a nonblank ALSA playback-device selector."""
        normalized = value.strip()

        if not normalized:
            raise ValueError(
                "forge.weather_alerts.audio_device must not be blank"
            )

        return normalized

    @model_validator(mode="after")
    def validate_location_freshness(
        self,
    ) -> Self:
        """Require safe GPS publication and startup ordering."""
        if self.location_publish_interval_s > self.refresh_interval_s:
            raise ValueError(
                "forge.weather_alerts.location_publish_interval_s "
                "must not exceed forge.weather_alerts.refresh_interval_s"
            )

        if self.enabled and self.refresh_on_start:
            raise ValueError(
                "forge.weather_alerts.refresh_on_start must remain "
                "false so current GPS publication can occur first"
            )

        return self


class ForgeConfig(ConfigurationModel):
    """Optional Pi-side Forge client settings."""

    enabled: bool = False
    api_url: AnyHttpUrl | None = None
    request_timeout_s: float = Field(default=5.0, gt=0, le=60)
    refresh_interval_s: float = Field(default=60.0, gt=0, le=3_600)
    refresh_on_start: bool = True
    max_response_bytes: int = Field(
        default=1_048_576,
        ge=1_024,
        le=16_777_216,
    )
    weather: ForgeWeatherClientConfig = ForgeWeatherClientConfig()
    weather_alerts: ForgeWeatherAlertClientConfig = (
        ForgeWeatherAlertClientConfig()
    )

    @model_validator(mode="after")
    def validate_enabled_forge(self) -> Self:
        """Require a Forge API URL and parent enablement for active Pi clients."""
        if self.enabled and self.api_url is None:
            raise ValueError(
                "forge.api_url must be configured when forge.enabled is true"
            )
        if self.weather.enabled and not self.enabled:
            raise ValueError(
                "forge.enabled must be true when forge.weather.enabled is true"
            )
        if self.weather_alerts.enabled and not self.enabled:
            raise ValueError(
                "forge.enabled must be true when "
                "forge.weather_alerts.enabled is true"
            )
        return self


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


class MapConfig(ConfigurationModel):
    """Optional live raster-map retrieval and local cache settings."""

    enabled: bool = False
    tile_url_template: str = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    zoom: int = Field(default=17, ge=0, le=22)
    request_timeout_s: float = Field(default=4.0, gt=0, le=60)
    gps_stale_after_s: float = Field(default=10.0, gt=0, le=300)
    cache_directory: Path = Path("data/map-tiles")
    cache_retention_days: int = Field(default=7, ge=7, le=365)
    maximum_cached_tiles: int = Field(default=2_048, ge=1, le=100_000)
    installed_packages: tuple[Path, ...] = ()
    style: MapPackageStyle = MapPackageStyle.DAY
    online_attribution: str = DEFAULT_MAP_ATTRIBUTION

    @field_validator("tile_url_template")
    @classmethod
    def validate_tile_url_template(cls, value: str) -> str:
        """Require an HTTP URL containing all standard tile placeholders."""
        normalized = value.strip()
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("must be an absolute HTTP or HTTPS URL")
        for token in ("{z}", "{x}", "{y}"):
            if token not in normalized:
                raise ValueError(f"must contain {token}")
        return normalized

    @field_validator("cache_directory", mode="before")
    @classmethod
    def validate_cache_directory(cls, value: object) -> object:
        """Reject empty or current-directory map cache paths."""
        if isinstance(value, str) and not value.strip():
            raise ValueError("must not be empty")
        if isinstance(value, (str, Path)) and str(Path(value)) == ".":
            raise ValueError("must name a cache directory")
        return value

    @field_validator("installed_packages")
    @classmethod
    def validate_installed_packages(
        cls,
        value: tuple[Path, ...],
    ) -> tuple[Path, ...]:
        """Require distinct MBTiles file paths without requiring installation yet."""
        normalized: list[Path] = []
        seen: set[Path] = set()

        for package_path in value:
            if str(package_path) in {"", "."}:
                raise ValueError("package paths must name MBTiles files")
            if package_path.suffix.lower() != ".mbtiles":
                raise ValueError(f"package path must end in .mbtiles: {package_path}")
            if package_path in seen:
                raise ValueError(f"duplicate installed package path: {package_path}")
            seen.add(package_path)
            normalized.append(package_path)

        return tuple(normalized)

    @field_validator("online_attribution")
    @classmethod
    def validate_online_attribution(cls, value: str) -> str:
        """Require visible attribution for online and cached map tiles."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized


class RadarConfig(ConfigurationModel):
    """Optional Pi-side weather-radar overlay settings."""

    enabled: bool = False
    manifest_refresh_interval_s: float = Field(default=60.0, gt=0, le=3_600)
    stale_after_s: float = Field(default=900.0, gt=0, le=86_400)
    hide_after_s: float = Field(default=1_800.0, gt=0, le=86_400)
    opacity: float = Field(default=0.55, gt=0, le=1)

    @model_validator(mode="after")
    def validate_freshness_window(self) -> Self:
        """Require the render cutoff to remain later than the stale threshold."""
        if self.hide_after_s <= self.stale_after_s:
            raise ValueError("radar.hide_after_s must exceed radar.stale_after_s")
        return self


class MeshCoreConfig(ConfigurationModel):
    """Optional receive-only MeshCore USB companion settings."""

    enabled: bool = False
    device: Path | None = None
    baud_rate: int = Field(default=115_200, ge=1, le=4_000_000)
    command_timeout_s: float = Field(default=2.0, gt=0, le=60)
    channels: tuple[str, ...] = ("#hamradio", "#skywarn", "#traffic")
    message_overlay_seconds: float = Field(default=20.0, gt=0, le=300)
    reconnect_delay_s: float = Field(default=2.0, gt=0, le=60)

    @field_validator("device", mode="before")
    @classmethod
    def validate_device(cls, value: object) -> object:
        """Require a stable absolute serial path when a device is supplied."""
        if value is None:
            return value
        if isinstance(value, str) and not value.strip():
            raise ValueError("must not be empty")
        path = Path(value) if isinstance(value, (str, Path)) else value
        if isinstance(path, Path) and not path.is_absolute():
            raise ValueError(
                "must be an absolute serial-device path under /dev/serial/..."
            )
        return path

    @field_validator("channels")
    @classmethod
    def validate_channels(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Normalize configured hashtag channels and reject ambiguity."""
        normalized: list[str] = []
        seen: set[str] = set()
        for channel in value:
            name = channel.strip().casefold()
            if not name.startswith("#") or len(name) < 2:
                raise ValueError("channel names must be nonblank hashtags such as #skywarn")
            if name in seen:
                raise ValueError(f"duplicate MeshCore channel: {name}")
            seen.add(name)
            normalized.append(name)
        if not normalized:
            raise ValueError("at least one MeshCore channel must be configured")
        return tuple(normalized)

    @model_validator(mode="after")
    def validate_enabled_device(self) -> Self:
        """Require one USB companion path when MeshCore receive is enabled."""
        if self.enabled and self.device is None:
            raise ValueError(
                "meshcore.device must be configured when meshcore.enabled is true"
            )
        return self


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
                raise ValueError("must be an absolute serial-device path, such as /dev/ttyACM0")
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
    dmr: DmrHotspotConfig = DmrHotspotConfig()
    pota_spots: PotaSpotsConfig = PotaSpotsConfig()
    map: MapConfig = MapConfig()
    radar: RadarConfig = RadarConfig()
    meshcore: MeshCoreConfig = MeshCoreConfig()
    physical_controls: PhysicalControlsConfig = PhysicalControlsConfig()
    storage: StorageConfig = StorageConfig()

    @model_validator(mode="after")
    def validate_radar_dependencies(self) -> Self:
        """Require cross-component dependencies for location-aware features."""
        if self.radar.enabled and not self.map.enabled:
            raise ValueError(
                "map.enabled must be true when radar.enabled is true"
            )
        if self.radar.enabled and not self.forge.enabled:
            raise ValueError(
                "forge.enabled must be true when radar.enabled is true"
            )
        if (
            self.forge.weather_alerts.enabled
            and self.hardware.effective_gps_mode
            is not HardwareAdapterMode.REAL
        ):
            raise ValueError(
                "hardware.gps_mode must be real when "
                "forge.weather_alerts.enabled is true"
            )
        return self


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


def resolve_dmr_private_key(
    config: ApplicationConfig,
    config_path: Path,
) -> Path | None:
    """Resolve the optional restricted DMR SSH key path."""
    private_key = config.dmr.private_key
    if private_key is None:
        return None
    expanded = private_key.expanduser()
    if expanded.is_absolute():
        return expanded
    return (config_path.parent / expanded).resolve()


def resolve_speech_model_path(
    config: ApplicationConfig,
    config_path: Path,
) -> Path | None:
    """Resolve the optional Vosk model path relative to the YAML file."""
    model_path = config.speech.model_path
    if model_path is None or model_path.is_absolute():
        return model_path
    return (config_path.parent / model_path).resolve()


def resolve_map_cache_directory(
    config: ApplicationConfig,
    config_path: Path,
) -> Path:
    """Resolve the map tile cache relative to the YAML file."""
    directory = config.map.cache_directory
    if directory.is_absolute():
        return directory
    return (config_path.parent / directory).resolve()


def resolve_map_package_paths(
    config: ApplicationConfig,
    config_path: Path,
) -> tuple[Path, ...]:
    """Resolve installed MBTiles paths relative to the YAML file."""
    return tuple(
        package_path
        if package_path.is_absolute()
        else (config_path.parent / package_path).resolve()
        for package_path in config.map.installed_packages
    )


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
    resolved_dmr = config.dmr.model_copy(
        update={"private_key": resolve_dmr_private_key(config, path)}
    )
    resolved_map = config.map.model_copy(
        update={
            "cache_directory": resolve_map_cache_directory(config, path),
            "installed_packages": resolve_map_package_paths(config, path),
        }
    )
    return config.model_copy(
        update={
            "storage": resolved_storage,
            "speech": resolved_speech,
            "dmr": resolved_dmr,
            "map": resolved_map,
        }
    )
