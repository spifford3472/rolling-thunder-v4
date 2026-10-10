"""Core domain models for Rolling Thunder contacts."""

import re
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_serializer,
    model_validator,
)

from rolling_thunder.value_types import (
    Callsign,
    MaidenheadGrid,
    PotaReference,
)

_SIGNAL_REPORT_PATTERN = re.compile(r"^(?:[1-5][1-9][1-9]?|[+-]?[0-9]{1,2})$")


class RadioMode(StrEnum):
    """Supported radio operating modes."""

    AM = "AM"
    CW = "CW"
    DATA = "DATA"
    DMR = "DMR"
    FT8 = "FT8"
    FM = "FM"
    LSB = "LSB"
    USB = "USB"


class GPSFixState(StrEnum):
    """Fix quality reported by a GPS adapter."""

    NO_FIX = "no_fix"
    TWO_DIMENSIONAL = "2d"
    THREE_DIMENSIONAL = "3d"


class RadioConnectionState(StrEnum):
    """Connection state reported by a radio adapter."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


class SynchronizationState(StrEnum):
    """Remote synchronization state for a locally stored contact."""

    PENDING = "pending"
    SYNCHRONIZED = "synchronized"
    FAILED = "failed"


class ContactGridSource(StrEnum):
    """Source used for a contacted station or location grid."""

    POTA_PARK = "pota_park"
    QRZ = "qrz"


class ContactEnrichmentState(StrEnum):
    """Whether optional post-commit metadata work is outstanding."""

    READY = "ready"
    PENDING_QRZ = "pending_qrz"


class ContactSource(StrEnum):
    """Operator workflow that originated a contact snapshot."""

    UNKNOWN = "unknown"
    POTA = "pota"
    DX = "dx"
    BROWSE = "browse"
    FT8 = "ft8"
    DMR = "dmr"


class DomainModel(BaseModel):
    """Base model shared by immutable Rolling Thunder domain objects."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        use_enum_values=False,
    )


class Frequency(DomainModel):
    """A validated radio frequency represented in integer hertz."""

    hz: int = Field(gt=0, le=300_000_000_000, strict=True)

    @property
    def khz(self) -> float:
        """Return the frequency in kilohertz."""
        return self.hz / 1_000

    @property
    def mhz(self) -> float:
        """Return the frequency in megahertz."""
        return self.hz / 1_000_000

    @model_serializer(mode="plain")
    def serialize_frequency(self) -> int:
        """Serialize frequency values as integer hertz."""
        return self.hz


class ContactWeatherObservation(DomainModel):
    """Optional provider-neutral weather captured for one end of a QSO."""

    summary: str = Field(min_length=1, max_length=240)
    provider_id: str | None = Field(default=None, max_length=80)
    provider_name: str | None = Field(default=None, max_length=128)
    observed_at: datetime | None = None
    fetched_at: datetime | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    longitude: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)
    condition: str | None = Field(default=None, max_length=80)
    temperature_c: float | None = Field(
        default=None, ge=-100, le=80, allow_inf_nan=False
    )
    relative_humidity_percent: float | None = Field(
        default=None, ge=0, le=100, allow_inf_nan=False
    )

    @field_validator("summary", "provider_id", "provider_name", "condition")
    @classmethod
    def normalize_weather_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("weather text must not be blank")
        return normalized

    @field_validator("observed_at", "fetched_at")
    @classmethod
    def normalize_weather_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("weather observation time must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_weather_coordinates(self) -> "ContactWeatherObservation":
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("weather latitude and longitude must be present together")
        return self


class RadioState(DomainModel):
    """Current state reported by a radio adapter."""

    connection_state: RadioConnectionState
    frequency: Frequency | None = None
    mode: RadioMode | None = None
    transmitting: bool = False
    updated_at: datetime
    last_error: str | None = Field(default=None, max_length=500)

    @field_validator("connection_state", mode="before")
    @classmethod
    def normalize_connection_state(cls, value: object) -> object:
        """Normalize string connection-state values."""
        if isinstance(value, str):
            return value.strip().lower()

        return value

    @field_validator("mode", mode="before")
    @classmethod
    def normalize_radio_mode(cls, value: object) -> object:
        """Normalize optional string mode values."""
        if isinstance(value, str):
            return value.strip().upper()

        return value

    @field_validator("updated_at")
    @classmethod
    def normalize_updated_at(cls, value: datetime) -> datetime:
        """Require a timezone-aware timestamp and normalize it to UTC."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("must include timezone information")

        return value.astimezone(UTC)

    @field_validator("last_error")
    @classmethod
    def normalize_last_error(cls, value: str | None) -> str | None:
        """Trim optional adapter errors and convert blank text to None."""
        if value is None:
            return None

        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_state_consistency(self) -> "RadioState":
        """Reject internally inconsistent radio states."""
        if self.connection_state is RadioConnectionState.CONNECTED:
            if self.frequency is None:
                raise ValueError("connected radio state requires a frequency")

            if self.mode is None:
                raise ValueError("connected radio state requires a mode")

        if self.transmitting:
            if self.connection_state is not RadioConnectionState.CONNECTED:
                raise ValueError("transmitting requires a connected radio")

            if self.frequency is None or self.mode is None:
                raise ValueError("transmitting requires a known frequency and mode")

        if self.connection_state is RadioConnectionState.ERROR and self.last_error is None:
            raise ValueError("error radio state requires last_error")

        return self

    @field_serializer("updated_at")
    def serialize_updated_at(self, value: datetime) -> str:
        """Serialize timestamps as unambiguous UTC ISO-8601 values."""
        return value.isoformat().replace("+00:00", "Z")


class GPSPosition(DomainModel):
    """Current position snapshot reported by a GPS adapter."""

    fix_state: GPSFixState
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    altitude_m: float | None = None
    speed_m_s: float | None = Field(default=None, ge=0)
    heading_degrees: float | None = Field(default=None, ge=0, lt=360)
    accuracy_m: float | None = Field(default=None, ge=0)
    satellites: int | None = Field(default=None, ge=0)
    updated_at: datetime

    @field_validator("fix_state", mode="before")
    @classmethod
    def normalize_fix_state(cls, value: object) -> object:
        """Normalize string GPS-fix values before enum validation."""
        if isinstance(value, str):
            return value.strip().lower()

        return value

    @field_validator("updated_at")
    @classmethod
    def normalize_gps_updated_at(cls, value: datetime) -> datetime:
        """Require a timezone-aware timestamp and normalize it to UTC."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("must include timezone information")

        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_fix_consistency(self) -> "GPSPosition":
        """Reject internally inconsistent GPS snapshots."""
        has_latitude = self.latitude is not None
        has_longitude = self.longitude is not None

        if has_latitude != has_longitude:
            raise ValueError(
                "latitude and longitude must either both be provided or both be absent"
            )

        if self.fix_state is GPSFixState.NO_FIX:
            if has_latitude or has_longitude:
                raise ValueError("no-fix GPS position cannot contain coordinates")

            if self.altitude_m is not None:
                raise ValueError("no-fix GPS position cannot contain altitude")

            if self.speed_m_s is not None or self.heading_degrees is not None:
                raise ValueError("no-fix GPS position cannot contain movement information")

        else:
            if not has_latitude or not has_longitude:
                raise ValueError("GPS fix requires latitude and longitude")

        if self.fix_state is GPSFixState.TWO_DIMENSIONAL and self.altitude_m is not None:
            raise ValueError("2d GPS fix cannot contain altitude")

        return self

    @field_serializer("updated_at")
    def serialize_gps_updated_at(self, value: datetime) -> str:
        """Serialize GPS timestamps as unambiguous UTC ISO-8601 values."""
        return value.isoformat().replace("+00:00", "Z")


class Contact(DomainModel):
    """A completed amateur-radio contact."""

    contact_id: UUID = Field(default_factory=uuid4)
    callsign: Callsign
    frequency_hz: int = Field(gt=0, le=300_000_000_000)
    mode: RadioMode
    started_at: datetime
    rst_sent: str
    rst_received: str
    grid: MaidenheadGrid | None = None
    contact_latitude: float | None = Field(default=None, ge=-90, le=90, strict=True)
    contact_longitude: float | None = Field(default=None, ge=-180, le=180, strict=True)
    my_grid: MaidenheadGrid | None = None
    my_latitude: float | None = Field(default=None, ge=-90, le=90, strict=True)
    my_longitude: float | None = Field(default=None, ge=-180, le=180, strict=True)
    my_state: str | None = None
    my_cq_zone: int | None = Field(default=None, ge=1, le=40, strict=True)
    my_itu_zone: int | None = Field(default=None, ge=1, le=90, strict=True)
    source: ContactSource = ContactSource.UNKNOWN
    tx_power_watts: int | None = Field(default=None, ge=1, le=1_500, strict=True)
    contact_weather: ContactWeatherObservation | None = None
    local_weather: ContactWeatherObservation | None = None
    weather_notes_enabled: bool = False
    pota_reference: PotaReference | None = None
    grid_source: ContactGridSource | None = None
    enrichment_state: ContactEnrichmentState = ContactEnrichmentState.READY
    notes: str | None = Field(default=None, max_length=2_000)
    synchronization_state: SynchronizationState = SynchronizationState.PENDING

    @property
    def my_grid6(self) -> MaidenheadGrid | None:
        """Return the one authoritative six-character local QSO grid."""
        return self.my_grid

    @property
    def my_grid4(self) -> str | None:
        """Return the station-routing prefix derived from ``my_grid6``."""
        return None if self.my_grid is None else str(self.my_grid)[:4]

    @field_validator("my_grid")
    @classmethod
    def require_six_character_local_grid(
        cls, value: MaidenheadGrid | None
    ) -> MaidenheadGrid | None:
        """Prevent independently supplied coarse/extended local-grid identities."""
        if value is not None and len(str(value)) != 6:
            raise ValueError("my_grid must be a six-character Maidenhead grid")
        return value

    @field_validator("mode", mode="before")
    @classmethod
    def normalize_mode(cls, value: object) -> object:
        """Normalize string mode values before enum validation."""
        if isinstance(value, str):
            return value.strip().upper()

        return value

    @field_validator("started_at")
    @classmethod
    def validate_started_at(cls, value: datetime) -> datetime:
        """Require a timezone-aware timestamp and normalize it to UTC."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("must include timezone information")

        return value.astimezone(UTC)

    @field_validator("rst_sent", "rst_received")
    @classmethod
    def validate_signal_report(cls, value: str) -> str:
        """Validate conventional voice, CW, and digital signal reports."""
        normalized = value.strip()

        if not _SIGNAL_REPORT_PATTERN.fullmatch(normalized):
            raise ValueError("must be a conventional report such as 59, 599, or -10")

        return normalized

    @field_validator("my_state", mode="before")
    @classmethod
    def normalize_my_state(cls, value: object) -> object:
        """Normalize optional local U.S. subdivision code."""
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("my_state must not be blank")
        if len(normalized) != 2 or not normalized.isalpha():
            raise ValueError("my_state must be a two-character code")
        return normalized

    @field_validator("grid_source", "enrichment_state", "source", mode="before")
    @classmethod
    def normalize_contact_enums(cls, value: object) -> object:
        """Normalize optional contact metadata enum strings."""
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str | None:
        """Trim optional notes and convert blank notes to None."""
        if value is None:
            return None

        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_contact_metadata(self) -> "Contact":
        """Reject contradictory contact-location metadata."""
        if (self.my_latitude is None) != (self.my_longitude is None):
            raise ValueError("my_latitude and my_longitude must be present together")
        if (self.contact_latitude is None) != (self.contact_longitude is None):
            raise ValueError(
                "contact_latitude and contact_longitude must be present together"
            )
        if self.contact_latitude is not None and self.grid is None:
            raise ValueError("contact coordinates require a contacted grid")

        jurisdiction_values = (self.my_state, self.my_cq_zone, self.my_itu_zone)
        if any(value is None for value in jurisdiction_values) and any(
            value is not None for value in jurisdiction_values
        ):
            raise ValueError("local jurisdiction fields must be present together")
        if self.my_state is not None and self.my_latitude is None:
            raise ValueError("local jurisdiction requires frozen local coordinates")

        if self.grid_source is not None and self.grid is None:
            raise ValueError("grid_source requires a contacted grid")

        if self.grid_source is ContactGridSource.POTA_PARK and self.pota_reference is None:
            raise ValueError("POTA park grid source requires pota_reference")

        if self.enrichment_state is ContactEnrichmentState.PENDING_QRZ and self.grid is not None:
            raise ValueError("pending QRZ enrichment requires an empty grid")

        return self

    @field_serializer("started_at")
    def serialize_started_at(self, value: datetime) -> str:
        """Serialize timestamps as an unambiguous UTC ISO-8601 value."""
        return value.isoformat().replace("+00:00", "Z")
