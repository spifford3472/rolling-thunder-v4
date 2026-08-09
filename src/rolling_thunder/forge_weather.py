"""Provider-neutral retained weather domain and refresh policy for Forge."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from math import asin, cos, radians, sin, sqrt
from threading import RLock
from typing import Final, Protocol

from pydantic import Field, field_validator, model_validator

from rolling_thunder.domain import DomainModel
from rolling_thunder.forge_mobile_location import (
    ForgeMobileLocationService,
    MobileLocationRecord,
)

_MAX_ERROR_LENGTH: Final = 500
Clock = Callable[[], datetime]


class ForgeWeatherProviderError(Exception):
    """Raised when a weather provider cannot return one complete valid snapshot."""


class ForgeWeatherStorageError(Exception):
    """Raised when retained Forge weather persistence cannot be used safely."""


class WeatherConditionToken(StrEnum):
    """Rolling Thunder-owned normalized weather condition semantics."""

    CLEAR = "clear"
    PARTLY_CLOUDY = "partly_cloudy"
    CLOUDY = "cloudy"
    FOG = "fog"
    DRIZZLE = "drizzle"
    RAIN = "rain"
    FREEZING_RAIN = "freezing_rain"
    SNOW = "snow"
    SHOWERS = "showers"
    THUNDERSTORM = "thunderstorm"
    UNKNOWN = "unknown"


class WeatherIconToken(StrEnum):
    """Rolling Thunder-owned icon tokens independent of provider weather codes."""

    CLEAR_DAY = "clear_day"
    CLEAR_NIGHT = "clear_night"
    PARTLY_CLOUDY_DAY = "partly_cloudy_day"
    PARTLY_CLOUDY_NIGHT = "partly_cloudy_night"
    CLOUDY = "cloudy"
    FOG = "fog"
    DRIZZLE = "drizzle"
    RAIN = "rain"
    FREEZING_RAIN = "freezing_rain"
    SNOW = "snow"
    SHOWERS = "showers"
    THUNDERSTORM = "thunderstorm"
    UNKNOWN = "unknown"


class WeatherProviderStatus(StrEnum):
    """Health of the Forge weather refresh path."""

    STARTING = "starting"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class WeatherSourceMetadata(DomainModel):
    """Provider attribution carried with retained weather data."""

    provider_id: str = Field(min_length=1, max_length=64)
    provider_name: str = Field(min_length=1, max_length=128)
    attribution_text: str = Field(min_length=1, max_length=256)
    attribution_url: str = Field(min_length=1, max_length=512)
    license_name: str = Field(min_length=1, max_length=128)
    license_url: str = Field(min_length=1, max_length=512)


class WeatherCurrent(DomainModel):
    """Normalized current weather fields required by Rolling Thunder."""

    temperature_c: float = Field(ge=-100.0, le=80.0, allow_inf_nan=False)
    relative_humidity_percent: float = Field(
        ge=0.0,
        le=100.0,
        allow_inf_nan=False,
    )
    condition: WeatherConditionToken
    icon: WeatherIconToken
    is_day: bool


class WeatherHourlyPoint(DomainModel):
    """One normalized future hourly forecast point."""

    forecast_at: datetime
    temperature_c: float = Field(ge=-100.0, le=80.0, allow_inf_nan=False)
    precipitation_probability_percent: float = Field(
        ge=0.0,
        le=100.0,
        allow_inf_nan=False,
    )

    @field_validator("forecast_at")
    @classmethod
    def normalize_forecast_at(cls, value: datetime) -> datetime:
        """Require timezone-aware timestamps and normalize to UTC."""
        return _normalize_timestamp(value, "forecast_at")


class WeatherSolar(DomainModel):
    """Sunrise and sunset timestamps associated with the retained forecast."""

    sunrise_at: datetime
    sunset_at: datetime

    @field_validator("sunrise_at", "sunset_at")
    @classmethod
    def normalize_solar_timestamp(cls, value: datetime) -> datetime:
        """Require timezone-aware timestamps and normalize to UTC."""
        return _normalize_timestamp(value, "solar timestamp")

    @model_validator(mode="after")
    def validate_order(self) -> WeatherSolar:
        """Reject impossible solar ordering."""
        if self.sunset_at <= self.sunrise_at:
            raise ValueError("sunset_at must be later than sunrise_at")
        return self


class WeatherSnapshot(DomainModel):
    """Complete provider-neutral weather snapshot retained by Forge."""

    latitude: float = Field(ge=-90.0, le=90.0, allow_inf_nan=False)
    longitude: float = Field(ge=-180.0, le=180.0, allow_inf_nan=False)
    source_at: datetime
    fetched_at: datetime
    current: WeatherCurrent
    hourly: tuple[WeatherHourlyPoint, ...] = Field(min_length=3, max_length=24)
    solar: WeatherSolar
    source: WeatherSourceMetadata

    @field_validator("source_at", "fetched_at")
    @classmethod
    def normalize_snapshot_timestamp(cls, value: datetime) -> datetime:
        """Require timezone-aware timestamps and normalize to UTC."""
        return _normalize_timestamp(value, "weather timestamp")

    @model_validator(mode="after")
    def validate_snapshot(self) -> WeatherSnapshot:
        """Require coherent source/fetch ordering and strictly advancing hours."""
        if self.source_at > self.fetched_at + timedelta(minutes=5):
            raise ValueError("source_at is implausibly later than fetched_at")
        previous: datetime | None = None
        for point in self.hourly:
            if previous is not None and point.forecast_at <= previous:
                raise ValueError("hourly forecast timestamps must strictly advance")
            previous = point.forecast_at
        return self


class ForgeWeatherState(DomainModel):
    """Immutable retained Forge weather state and truthful refresh health."""

    revision: int = Field(ge=0)
    snapshot: WeatherSnapshot | None = None
    provider_status: WeatherProviderStatus = WeatherProviderStatus.STARTING
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = Field(default=None, max_length=_MAX_ERROR_LENGTH)
    startup_storage_error: str | None = Field(default=None, max_length=_MAX_ERROR_LENGTH)
    persistence_error: str | None = Field(default=None, max_length=_MAX_ERROR_LENGTH)

    @field_validator("last_attempt_at", "last_success_at")
    @classmethod
    def normalize_optional_timestamp(cls, value: datetime | None) -> datetime | None:
        """Normalize optional provider-health timestamps to UTC."""
        if value is None:
            return None
        return _normalize_timestamp(value, "provider-health timestamp")

    @field_validator("last_error", "startup_storage_error", "persistence_error")
    @classmethod
    def normalize_optional_error(cls, value: str | None) -> str | None:
        """Trim and bound optional diagnostics."""
        if value is None:
            return None
        normalized = value.strip()
        return normalized[:_MAX_ERROR_LENGTH] or None

    @model_validator(mode="after")
    def validate_retained_state(self) -> ForgeWeatherState:
        """Keep retained revision and snapshot presence consistent."""
        if self.revision == 0 and self.snapshot is not None:
            raise ValueError("revision 0 cannot contain a weather snapshot")
        if self.revision > 0 and self.snapshot is None:
            raise ValueError("positive weather revision requires a snapshot")
        return self


class WeatherProvider(Protocol):
    """Synchronous provider boundary executed only by the weather worker."""

    def fetch_weather(self, location: MobileLocationRecord) -> WeatherSnapshot:
        """Return one complete normalized weather snapshot for a location."""
        ...


class ForgeWeatherRepository(Protocol):
    """Durable retained-weather boundary consumed by the weather service."""

    def load(self) -> ForgeWeatherState | None:
        """Load and revalidate the latest retained weather snapshot."""
        ...

    def replace(self, snapshot: WeatherSnapshot) -> ForgeWeatherState:
        """Transactionally persist one complete replacement snapshot."""
        ...


class ForgeWeatherService:
    """Apply deterministic refresh policy, persist first, then publish state."""

    def __init__(
        self,
        provider: WeatherProvider,
        repository: ForgeWeatherRepository,
        mobile_location: ForgeMobileLocationService,
        *,
        now: Clock | None = None,
        max_forecast_age_s: float = 1_800.0,
        movement_refresh_km: float = 10.0,
    ) -> None:
        if max_forecast_age_s <= 0:
            raise ValueError("Weather maximum forecast age must be positive.")
        if movement_refresh_km <= 0:
            raise ValueError("Weather movement refresh distance must be positive.")
        self._provider = provider
        self._repository = repository
        self._mobile_location = mobile_location
        self._now = now or (lambda: datetime.now(UTC))
        self._max_forecast_age_s = max_forecast_age_s
        self._movement_refresh_km = movement_refresh_km
        self._lock = RLock()

        startup_error: str | None
        try:
            stored = repository.load()
        except ForgeWeatherStorageError as error:
            stored = None
            startup_error = self._bounded_error(error)
        else:
            startup_error = None

        if stored is None:
            self._state = ForgeWeatherState(
                revision=0,
                provider_status=(
                    WeatherProviderStatus.UNAVAILABLE
                    if startup_error is not None
                    else WeatherProviderStatus.STARTING
                ),
                startup_storage_error=startup_error,
            )
        else:
            self._state = stored.model_copy(
                update={
                    "provider_status": WeatherProviderStatus.STARTING,
                    "startup_storage_error": startup_error,
                    "persistence_error": None,
                    "last_error": None,
                }
            )

    def get_state(self) -> ForgeWeatherState:
        """Return already-published weather state without provider or storage I/O."""
        with self._lock:
            return self._state

    def is_stale(self) -> bool:
        """Return whether retained weather is absent, aged out, or spatially stale."""
        now = self._aware_now()
        with self._lock:
            state = self._state
        snapshot = state.snapshot
        if snapshot is None:
            return True
        if now - snapshot.fetched_at >= timedelta(seconds=self._max_forecast_age_s):
            return True
        location_state = self._mobile_location.get_state()
        location = location_state.location
        if location is None:
            return False
        return (
            _distance_km(
                snapshot.latitude,
                snapshot.longitude,
                location.latitude,
                location.longitude,
            )
            >= self._movement_refresh_km
        )

    def refresh_if_needed(self, *, force: bool = False) -> ForgeWeatherState:
        """Refresh only when missing, aged, moved, or explicitly forced."""
        now = self._aware_now()
        location = self._mobile_location.get_state().location
        with self._lock:
            previous = self._state

        if location is None:
            status = (
                WeatherProviderStatus.DEGRADED
                if previous.snapshot is not None
                else WeatherProviderStatus.UNAVAILABLE
            )
            return self._publish_state(
                previous.model_copy(
                    update={
                        "provider_status": status,
                        "last_error": "No retained mobile location is available for weather refresh.",
                    }
                )
            )

        if not force and not self._refresh_required(previous.snapshot, location, now):
            return previous

        try:
            candidate = self._provider.fetch_weather(location)
        except (ForgeWeatherProviderError, ValueError) as error:
            return self._publish_failed_attempt(previous, now, error)

        if (
            abs(candidate.latitude - location.latitude) > 1e-6
            or abs(candidate.longitude - location.longitude) > 1e-6
        ):
            return self._publish_failed_attempt(
                previous,
                now,
                ForgeWeatherProviderError(
                    "Weather provider returned coordinates that do not match the requested location."
                ),
            )

        try:
            stored = self._repository.replace(candidate)
        except ForgeWeatherStorageError as error:
            status = (
                WeatherProviderStatus.DEGRADED
                if previous.snapshot is not None
                else WeatherProviderStatus.UNAVAILABLE
            )
            return self._publish_state(
                previous.model_copy(
                    update={
                        "provider_status": status,
                        "last_attempt_at": now,
                        "persistence_error": self._bounded_error(error),
                    }
                )
            )

        return self._publish_state(
            stored.model_copy(
                update={
                    "provider_status": WeatherProviderStatus.HEALTHY,
                    "last_attempt_at": now,
                    "last_success_at": now,
                    "last_error": None,
                    "startup_storage_error": None,
                    "persistence_error": None,
                }
            )
        )

    def _refresh_required(
        self,
        snapshot: WeatherSnapshot | None,
        location: MobileLocationRecord,
        now: datetime,
    ) -> bool:
        if snapshot is None:
            return True
        if now - snapshot.fetched_at >= timedelta(seconds=self._max_forecast_age_s):
            return True
        return (
            _distance_km(
                snapshot.latitude,
                snapshot.longitude,
                location.latitude,
                location.longitude,
            )
            >= self._movement_refresh_km
        )

    def _publish_failed_attempt(
        self,
        previous: ForgeWeatherState,
        now: datetime,
        error: BaseException,
    ) -> ForgeWeatherState:
        status = (
            WeatherProviderStatus.DEGRADED
            if previous.snapshot is not None
            else WeatherProviderStatus.UNAVAILABLE
        )
        return self._publish_state(
            previous.model_copy(
                update={
                    "provider_status": status,
                    "last_attempt_at": now,
                    "last_error": self._bounded_error(error),
                }
            )
        )

    def _publish_state(self, state: ForgeWeatherState) -> ForgeWeatherState:
        with self._lock:
            self._state = state
            return self._state

    def _aware_now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Forge weather clock must be timezone-aware")
        return value.astimezone(UTC)

    @staticmethod
    def _bounded_error(error: BaseException) -> str:
        text = str(error).strip() or error.__class__.__name__
        return text[:_MAX_ERROR_LENGTH]


def _normalize_timestamp(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include timezone information")
    return value.astimezone(UTC)


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance between two WGS84 coordinates."""
    earth_radius_km = 6_371.0088
    lat1_r = radians(lat1)
    lat2_r = radians(lat2)
    delta_lat = radians(lat2 - lat1)
    delta_lon = radians(lon2 - lon1)
    a = (
        sin(delta_lat / 2.0) ** 2
        + cos(lat1_r) * cos(lat2_r) * sin(delta_lon / 2.0) ** 2
    )
    return 2.0 * earth_radius_km * asin(sqrt(a))
