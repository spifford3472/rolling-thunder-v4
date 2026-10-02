"""Project-owned immutable FT8 domain models."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from uuid import UUID, uuid4

from pydantic import TypeAdapter

from rolling_thunder.value_types import Callsign, MaidenheadGrid

_CALLSIGN_ADAPTER = TypeAdapter(Callsign)
_GRID_ADAPTER = TypeAdapter(MaidenheadGrid)
FT8_PERIOD_SECONDS = 15


class FT8PeriodParity(StrEnum):
    """Even/odd identity for UTC-aligned FT8 periods."""

    EVEN = "even"
    ODD = "odd"


@dataclass(frozen=True, slots=True, order=True)
class FT8Period:
    """One stable UTC-aligned 15-second FT8 period."""

    index: int

    def __post_init__(self) -> None:
        if self.index < 0:
            raise ValueError("FT8 period index must be non-negative")

    @classmethod
    def from_utc(cls, value: datetime) -> "FT8Period":
        """Map an aware datetime to its containing UTC FT8 period."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("FT8 period time must be timezone-aware")
        timestamp = value.astimezone(UTC).timestamp()
        if timestamp < 0:
            raise ValueError("FT8 period time must be at or after the Unix epoch")
        return cls(index=int(timestamp) // FT8_PERIOD_SECONDS)

    @property
    def start_utc(self) -> datetime:
        """UTC start of this period."""
        return datetime.fromtimestamp(self.index * FT8_PERIOD_SECONDS, tz=UTC)

    @property
    def parity(self) -> FT8PeriodParity:
        """Return even/odd slot parity from stable period identity."""
        return FT8PeriodParity.EVEN if self.index % 2 == 0 else FT8PeriodParity.ODD


class FT8MessageKind(StrEnum):
    """Normalized receive-message categories used by application logic."""

    CQ = "cq"
    REPORT = "report"
    R_REPORT = "r_report"
    ACK_73 = "73"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class FT8Decode:
    """Decoder-independent immutable FT8 decode."""

    period: FT8Period
    snr_db: int
    dt_seconds: float
    audio_frequency_hz: int
    raw_message: str
    kind: FT8MessageKind
    source_callsign: str | None = None
    destination_callsign: str | None = None
    grid: str | None = None
    report_db: int | None = None
    cq_qualifier: str | None = None
    backend_metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        raw_message = self.raw_message.strip()
        if not raw_message:
            raise ValueError("FT8 decode raw_message must not be blank")
        if self.audio_frequency_hz <= 0:
            raise ValueError("FT8 decode audio_frequency_hz must be positive")
        object.__setattr__(self, "raw_message", raw_message)
        if self.source_callsign is not None:
            object.__setattr__(
                self,
                "source_callsign",
                _CALLSIGN_ADAPTER.validate_python(self.source_callsign),
            )
        if self.destination_callsign is not None:
            object.__setattr__(
                self,
                "destination_callsign",
                _CALLSIGN_ADAPTER.validate_python(self.destination_callsign),
            )
        if self.grid is not None:
            object.__setattr__(self, "grid", _GRID_ADAPTER.validate_python(self.grid))
        if self.cq_qualifier is not None:
            qualifier = self.cq_qualifier.strip().upper()
            object.__setattr__(self, "cq_qualifier", qualifier or None)
        object.__setattr__(
            self,
            "backend_metadata",
            MappingProxyType(dict(self.backend_metadata)),
        )


@dataclass(frozen=True, slots=True)
class FT8CQActivity:
    """Immutable browser-oriented CQ activity snapshot item."""

    callsign: str
    last_cq: FT8Period
    last_any_decode: FT8Period
    cq_count: int
    snr_db: int
    dt_seconds: float
    audio_frequency_hz: int
    grid: str | None = None
    cq_qualifier: str | None = None
    pota_cq: bool = False
    active_non_cq: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "callsign",
            _CALLSIGN_ADAPTER.validate_python(self.callsign),
        )
        if self.grid is not None:
            object.__setattr__(self, "grid", _GRID_ADAPTER.validate_python(self.grid))
        if self.audio_frequency_hz <= 0:
            raise ValueError("FT8 CQ audio_frequency_hz must be positive")
        if self.cq_count < 1:
            raise ValueError("FT8 CQ count must be at least 1")
        if self.last_any_decode < self.last_cq:
            raise ValueError("FT8 last_any_decode cannot precede last_cq")

    @property
    def last_period(self) -> FT8Period:
        """Compatibility alias for the most recent CQ period."""
        return self.last_cq


@dataclass(frozen=True, slots=True)
class FT8QsoContext:
    """Frozen authorization snapshot for exactly one operator-selected QSO."""

    local_callsign: str
    remote_callsign: str
    target_audio_frequency_hz: int
    radio_frequency_hz: int
    radio_band: str
    radio_mode: str
    local_grid: str
    tx_parity: FT8PeriodParity
    authorized_period: FT8Period
    authorized_utc: datetime
    signal_report_db: int
    latitude: float | None = None
    longitude: float | None = None
    location_label: str | None = None
    remote_grid: str | None = None
    qso_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "local_callsign",
            _CALLSIGN_ADAPTER.validate_python(self.local_callsign),
        )
        object.__setattr__(
            self,
            "remote_callsign",
            _CALLSIGN_ADAPTER.validate_python(self.remote_callsign),
        )
        object.__setattr__(self, "local_grid", _GRID_ADAPTER.validate_python(self.local_grid))
        if self.remote_grid is not None:
            object.__setattr__(
                self,
                "remote_grid",
                _GRID_ADAPTER.validate_python(self.remote_grid),
            )
        if self.target_audio_frequency_hz <= 0:
            raise ValueError("target_audio_frequency_hz must be positive")
        if not -50 <= self.signal_report_db <= 49:
            raise ValueError("signal_report_db must be between -50 and +49 dB")
        if self.radio_frequency_hz <= 0:
            raise ValueError("radio_frequency_hz must be positive")
        if not self.radio_band.strip():
            raise ValueError("radio_band must not be blank")
        if not self.radio_mode.strip():
            raise ValueError("radio_mode must not be blank")
        if self.authorized_utc.tzinfo is None or self.authorized_utc.utcoffset() is None:
            raise ValueError("authorized_utc must be timezone-aware")
        normalized_utc = self.authorized_utc.astimezone(UTC)
        object.__setattr__(self, "authorized_utc", normalized_utc)
        if FT8Period.from_utc(normalized_utc) != self.authorized_period:
            raise ValueError("authorized_utc must fall within authorized_period")
        if self.latitude is not None and not -90 <= self.latitude <= 90:
            raise ValueError("latitude must be between -90 and 90")
        if self.longitude is not None and not -180 <= self.longitude <= 180:
            raise ValueError("longitude must be between -180 and 180")
        if self.location_label is not None:
            label = self.location_label.strip()
            object.__setattr__(self, "location_label", label or None)


class FT8QsoState(StrEnum):
    """Explicit hardware-independent FT8 QSO application states."""

    IDLE = "idle"
    AUTHORIZED = "authorized"
    WAIT_TX_CALL = "wait_tx_call"
    TX_CALL = "tx_call"
    WAIT_REPORT = "wait_report"
    TX_REPORT = "tx_report"
    WAIT_R_REPORT = "wait_r_report"
    TX_R_REPORT = "tx_r_report"
    WAIT_73 = "wait_73"
    TX_73 = "tx_73"
    COMPLETED = "completed"
    ABORTED = "aborted"
    RETRY_EXHAUSTED = "retry_exhausted"
    ERROR = "error"
