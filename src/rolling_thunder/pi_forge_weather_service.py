"""Thread-safe Pi service for durable retained Forge weather state."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from threading import RLock
from typing import Protocol

from pydantic import Field, field_validator, model_validator

from rolling_thunder.domain import DomainModel
from rolling_thunder.forge_weather import WeatherSnapshot
from rolling_thunder.forge_weather_client import (
    ForgeRemoteWeatherHealth,
    ForgeWeatherClientResult,
    ForgeWeatherClientTransportError,
    ForgeWeatherClientValidationError,
)
from rolling_thunder.storage import StorageError

_MAX_ERROR_LENGTH = 500
Clock = Callable[[], datetime]


class ForgeWeatherClient(Protocol):
    """Complete retained-weather client consumed by the Pi service."""

    def fetch_weather(self) -> ForgeWeatherClientResult:
        """Fetch one complete validated Forge weather result."""
        ...


class ForgeWeatherCache(Protocol):
    """Durable last-good weather boundary consumed by the Pi service."""

    def load(self) -> ForgeWeatherClientResult | None:
        """Load the latest complete cached weather result, if present."""
        ...

    def replace(self, result: ForgeWeatherClientResult) -> None:
        """Transactionally replace the cached last-good weather result."""
        ...


class PiForgeWeatherStateKind(StrEnum):
    """Origin/availability state of the currently published Pi weather."""

    DISABLED = "disabled"
    NO_DATA = "no_data"
    LIVE = "live"
    RETAINED = "retained"


class PiForgeWeatherErrorKind(StrEnum):
    """Failure categories retained independently from usable weather data."""

    STORAGE_READ = "storage_read"
    STORAGE_WRITE = "storage_write"
    TRANSPORT = "transport"
    VALIDATION = "validation"


class PiForgeWeatherState(DomainModel):
    """Immutable application-facing retained weather state on the Pi."""

    kind: PiForgeWeatherStateKind
    snapshot_revision: int | None = Field(default=None, ge=1, strict=True)
    snapshot: WeatherSnapshot | None = None
    health: ForgeRemoteWeatherHealth | None = None
    stale: bool = False
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    error_kind: PiForgeWeatherErrorKind | None = None
    last_error: str | None = Field(default=None, max_length=_MAX_ERROR_LENGTH)

    @field_validator("last_attempt_at", "last_success_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Pi Forge weather timestamps must include timezone information")
        return value.astimezone(UTC)

    @field_validator("last_error")
    @classmethod
    def normalize_error(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized[:_MAX_ERROR_LENGTH] or None

    @model_validator(mode="after")
    def validate_consistency(self) -> PiForgeWeatherState:
        has_snapshot = self.snapshot is not None
        if has_snapshot != (self.snapshot_revision is not None):
            raise ValueError("weather snapshot and revision must be present together")

        if self.kind is PiForgeWeatherStateKind.DISABLED:
            if any(
                value is not None
                for value in (
                    self.snapshot_revision,
                    self.snapshot,
                    self.health,
                    self.last_attempt_at,
                    self.last_success_at,
                    self.error_kind,
                    self.last_error,
                )
            ) or self.stale:
                raise ValueError("disabled weather state cannot contain runtime data")
            return self

        if self.kind is PiForgeWeatherStateKind.NO_DATA and has_snapshot:
            raise ValueError("no-data weather state cannot contain a snapshot")
        if self.kind in {PiForgeWeatherStateKind.LIVE, PiForgeWeatherStateKind.RETAINED}:
            if not has_snapshot:
                raise ValueError("live/retained weather state requires a snapshot")

        if self.kind is PiForgeWeatherStateKind.LIVE:
            if self.last_attempt_at is None or self.last_success_at is None:
                raise ValueError("live weather requires attempt and success timestamps")
            if self.health is None:
                raise ValueError("live weather requires current Forge health")
            if self.health.revision != self.snapshot_revision:
                raise ValueError("live weather health revision must match snapshot revision")
            if self.error_kind is not None or self.last_error is not None:
                raise ValueError("live weather cannot contain a local error")

        if self.kind is PiForgeWeatherStateKind.RETAINED:
            if self.last_success_at is None:
                raise ValueError("retained weather requires a prior success timestamp")

        if (self.error_kind is None) != (self.last_error is None):
            raise ValueError("weather error kind and error text must be present together")

        return self

    @classmethod
    def disabled(cls) -> PiForgeWeatherState:
        """Return the explicit immutable state for a disabled Pi weather client."""
        return cls(kind=PiForgeWeatherStateKind.DISABLED)

    @property
    def has_usable_snapshot(self) -> bool:
        """Return whether callers may consume a weather snapshot."""
        return self.snapshot is not None

    @property
    def source_at(self) -> datetime | None:
        """Return provider source time without resetting age on the Pi."""
        return self.snapshot.source_at if self.snapshot is not None else None


class PiForgeWeatherService:
    """Fetch, persist, and atomically publish retained Forge weather."""

    def __init__(
        self,
        client: ForgeWeatherClient,
        cache: ForgeWeatherCache,
        *,
        now: Clock | None = None,
        stale_after_s: float = 1_800.0,
    ) -> None:
        if stale_after_s <= 0:
            raise ValueError("Pi Forge weather stale threshold must be positive.")
        self._client = client
        self._cache = cache
        self._now = now or (lambda: datetime.now(UTC))
        self._stale_after = timedelta(seconds=stale_after_s)
        self._lock = RLock()
        self._refreshing = False
        self._state = self._load_initial_state()

    @property
    def is_refreshing(self) -> bool:
        """Return whether one weather refresh is executing."""
        with self._lock:
            return self._refreshing

    def get_state(self) -> PiForgeWeatherState:
        """Return the latest immutable state without network or storage I/O."""
        with self._lock:
            return self._state

    def refresh(self) -> PiForgeWeatherState:
        """Fetch weather off-thread; persist before publishing any new snapshot."""
        with self._lock:
            if self._refreshing:
                return self._state
            self._refreshing = True
            previous = self._state

        try:
            attempted_at = self._aware_now()
            try:
                result = self._client.fetch_weather()
            except ForgeWeatherClientTransportError as error:
                return self._publish_failure(
                    previous,
                    attempted_at=attempted_at,
                    error_kind=PiForgeWeatherErrorKind.TRANSPORT,
                    error=error,
                )
            except ForgeWeatherClientValidationError as error:
                return self._publish_failure(
                    previous,
                    attempted_at=attempted_at,
                    error_kind=PiForgeWeatherErrorKind.VALIDATION,
                    error=error,
                )

            if result.snapshot is None:
                return self._publish_no_data(previous, result, attempted_at=attempted_at)

            try:
                self._cache.replace(result)
            except StorageError as error:
                return self._publish_failure(
                    previous,
                    attempted_at=attempted_at,
                    error_kind=PiForgeWeatherErrorKind.STORAGE_WRITE,
                    error=error,
                )

            state = PiForgeWeatherState(
                kind=PiForgeWeatherStateKind.LIVE,
                snapshot_revision=result.revision,
                snapshot=result.snapshot,
                health=result.health,
                stale=self._is_result_stale(result, attempted_at),
                last_attempt_at=attempted_at,
                last_success_at=result.received_at,
            )
            return self._publish(state)
        finally:
            with self._lock:
                self._refreshing = False

    def _load_initial_state(self) -> PiForgeWeatherState:
        try:
            result = self._cache.load()
        except StorageError as error:
            return PiForgeWeatherState(
                kind=PiForgeWeatherStateKind.NO_DATA,
                error_kind=PiForgeWeatherErrorKind.STORAGE_READ,
                last_error=self._bounded_error(error),
            )

        if result is None or result.snapshot is None:
            return PiForgeWeatherState(kind=PiForgeWeatherStateKind.NO_DATA)

        now = self._aware_now()
        return PiForgeWeatherState(
            kind=PiForgeWeatherStateKind.RETAINED,
            snapshot_revision=result.revision,
            snapshot=result.snapshot,
            health=result.health,
            stale=self._is_result_stale(result, now),
            last_success_at=result.received_at,
        )

    def _publish_no_data(
        self,
        previous: PiForgeWeatherState,
        result: ForgeWeatherClientResult,
        *,
        attempted_at: datetime,
    ) -> PiForgeWeatherState:
        if previous.snapshot is None:
            return self._publish(
                PiForgeWeatherState(
                    kind=PiForgeWeatherStateKind.NO_DATA,
                    health=result.health,
                    stale=True,
                    last_attempt_at=attempted_at,
                    last_success_at=result.received_at,
                )
            )

        return self._publish(
            PiForgeWeatherState(
                kind=PiForgeWeatherStateKind.RETAINED,
                snapshot_revision=previous.snapshot_revision,
                snapshot=previous.snapshot,
                health=result.health,
                stale=True,
                last_attempt_at=attempted_at,
                last_success_at=previous.last_success_at,
            )
        )

    def _publish_failure(
        self,
        previous: PiForgeWeatherState,
        *,
        attempted_at: datetime,
        error_kind: PiForgeWeatherErrorKind,
        error: BaseException,
    ) -> PiForgeWeatherState:
        if previous.snapshot is None:
            state = PiForgeWeatherState(
                kind=PiForgeWeatherStateKind.NO_DATA,
                health=previous.health,
                stale=True,
                last_attempt_at=attempted_at,
                last_success_at=previous.last_success_at,
                error_kind=error_kind,
                last_error=self._bounded_error(error),
            )
        else:
            stale = self._snapshot_is_stale(previous.snapshot, attempted_at) or previous.stale
            state = PiForgeWeatherState(
                kind=PiForgeWeatherStateKind.RETAINED,
                snapshot_revision=previous.snapshot_revision,
                snapshot=previous.snapshot,
                health=previous.health,
                stale=stale,
                last_attempt_at=attempted_at,
                last_success_at=previous.last_success_at,
                error_kind=error_kind,
                last_error=self._bounded_error(error),
            )
        return self._publish(state)

    def _is_result_stale(self, result: ForgeWeatherClientResult, now: datetime) -> bool:
        snapshot = result.snapshot
        if snapshot is None:
            return True
        return result.stale or self._snapshot_is_stale(snapshot, now)

    def _snapshot_is_stale(self, snapshot: WeatherSnapshot, now: datetime) -> bool:
        return now - snapshot.source_at >= self._stale_after

    def _publish(self, state: PiForgeWeatherState) -> PiForgeWeatherState:
        with self._lock:
            self._state = state
            return self._state

    def _aware_now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Pi Forge weather clock must return an aware datetime")
        return value.astimezone(UTC)

    @staticmethod
    def _bounded_error(error: BaseException) -> str:
        text = str(error).strip() or error.__class__.__name__
        return text[:_MAX_ERROR_LENGTH]
