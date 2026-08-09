"""Thread-safe retained Forge weather-alert state for the Raspberry Pi."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from threading import RLock
from typing import Protocol

from pydantic import Field, field_validator, model_validator

from rolling_thunder.domain import DomainModel
from rolling_thunder.forge_weather_alert_client import (
    ForgeRemoteWeatherAlertHealth,
    ForgeWeatherAlertClientResult,
    ForgeWeatherAlertClientTransportError,
    ForgeWeatherAlertClientValidationError,
)
from rolling_thunder.forge_weather_alerts import (
    WeatherAlertApplicability,
    WeatherAlertSnapshot,
)
from rolling_thunder.storage import StorageError

_MAX_ERROR_LENGTH = 500
Clock = Callable[[], datetime]


class ForgeWeatherAlertClient(Protocol):
    """Validated private-Forge alert client used by the Pi service."""

    def fetch_alerts(self) -> ForgeWeatherAlertClientResult:
        """Fetch one complete retained Forge weather-alert response."""
        ...


class ForgeWeatherAlertCache(Protocol):
    """Durable last-good Pi alert cache."""

    def load(self) -> ForgeWeatherAlertClientResult | None:
        """Load the latest complete retained response."""
        ...

    def replace(
        self,
        result: ForgeWeatherAlertClientResult,
    ) -> None:
        """Transactionally replace the retained response."""
        ...


class PiForgeWeatherAlertStateKind(StrEnum):
    """Origin/availability of the currently published Pi alert state."""

    DISABLED = "disabled"
    NO_DATA = "no_data"
    LIVE = "live"
    RETAINED = "retained"


class PiForgeWeatherAlertErrorKind(StrEnum):
    """Local Pi alert-client failure category."""

    STORAGE_READ = "storage_read"
    STORAGE_WRITE = "storage_write"
    TRANSPORT = "transport"
    VALIDATION = "validation"


class PiForgeWeatherAlertState(DomainModel):
    """Immutable application-facing Pi severe-weather alert state."""

    kind: PiForgeWeatherAlertStateKind
    snapshot_revision: int | None = Field(
        default=None,
        ge=1,
        strict=True,
    )
    snapshot: WeatherAlertSnapshot | None = None
    health: ForgeRemoteWeatherAlertHealth | None = None

    # This is deliberately separate from retained Forge health.
    # A local transport failure immediately downgrades applicability.
    applicability: WeatherAlertApplicability = (
        WeatherAlertApplicability.UNAVAILABLE
    )

    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None

    error_kind: PiForgeWeatherAlertErrorKind | None = None
    last_error: str | None = Field(
        default=None,
        max_length=_MAX_ERROR_LENGTH,
    )

    @field_validator(
        "last_attempt_at",
        "last_success_at",
    )
    @classmethod
    def normalize_timestamp(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        if value is None:
            return None

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(
                "Pi weather-alert timestamps must include timezone information"
            )

        return value.astimezone(UTC)

    @field_validator("last_error")
    @classmethod
    def normalize_error(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        normalized = value.strip()
        return normalized[:_MAX_ERROR_LENGTH] or None

    @model_validator(mode="after")
    def validate_consistency(
        self,
    ) -> PiForgeWeatherAlertState:
        has_snapshot = self.snapshot is not None

        if has_snapshot != (self.snapshot_revision is not None):
            raise ValueError(
                "weather-alert snapshot and revision must be present together"
            )

        if self.kind is PiForgeWeatherAlertStateKind.DISABLED:
            if (
                has_snapshot
                or self.health is not None
                or self.last_attempt_at is not None
                or self.last_success_at is not None
                or self.error_kind is not None
                or self.last_error is not None
                or self.applicability
                is not WeatherAlertApplicability.UNAVAILABLE
            ):
                raise ValueError(
                    "disabled weather-alert state cannot contain runtime data"
                )
            return self

        if (
            self.kind is PiForgeWeatherAlertStateKind.NO_DATA
            and has_snapshot
        ):
            raise ValueError(
                "no-data weather-alert state cannot contain a snapshot"
            )

        if (
            self.kind is PiForgeWeatherAlertStateKind.RETAINED
            and not has_snapshot
        ):
            raise ValueError(
                "retained weather-alert state requires a snapshot"
            )

        if (
            self.kind is PiForgeWeatherAlertStateKind.RETAINED
            and self.applicability
            is not WeatherAlertApplicability.RETAINED_UNVERIFIED
        ):
            raise ValueError(
                "retained Pi alerts must be location-unverified"
            )

        if (
            self.applicability
            is WeatherAlertApplicability.VERIFIED_CURRENT
            and (
                self.kind is not PiForgeWeatherAlertStateKind.LIVE
                or not has_snapshot
            )
        ):
            raise ValueError(
                "verified-current Pi alerts require a live snapshot"
            )

        if (
            self.kind is PiForgeWeatherAlertStateKind.NO_DATA
            and self.applicability
            is not WeatherAlertApplicability.UNAVAILABLE
        ):
            raise ValueError(
                "no-data Pi alerts must have unavailable applicability"
            )

        if self.kind is PiForgeWeatherAlertStateKind.LIVE:
            if self.health is None:
                raise ValueError(
                    "live Pi weather-alert state requires Forge health"
                )
            if self.last_attempt_at is None:
                raise ValueError(
                    "live Pi weather-alert state requires an attempt timestamp"
                )
            if self.last_success_at is None:
                raise ValueError(
                    "live Pi weather-alert state requires a success timestamp"
                )
            if self.error_kind is not None or self.last_error is not None:
                raise ValueError(
                    "live Pi weather-alert state cannot contain local errors"
                )

        if (
            self.kind is PiForgeWeatherAlertStateKind.RETAINED
            and self.last_success_at is None
        ):
            raise ValueError(
                "retained Pi weather alerts require a prior success timestamp"
            )

        if (self.error_kind is None) != (self.last_error is None):
            raise ValueError(
                "weather-alert error kind and text must appear together"
            )

        return self

    @classmethod
    def disabled(cls) -> PiForgeWeatherAlertState:
        """Return explicit immutable disabled state."""
        return cls(
            kind=PiForgeWeatherAlertStateKind.DISABLED,
        )

    @property
    def is_verified_current(self) -> bool:
        """Return whether alerts are verified for the current vehicle point."""
        return (
            self.kind is PiForgeWeatherAlertStateKind.LIVE
            and self.snapshot is not None
            and self.applicability
            is WeatherAlertApplicability.VERIFIED_CURRENT
        )


class PiForgeWeatherAlertService:
    """Fetch, retain, and atomically publish Forge weather-alert state."""

    def __init__(
        self,
        client: ForgeWeatherAlertClient,
        cache: ForgeWeatherAlertCache,
        *,
        now: Clock | None = None,
    ) -> None:
        self._client = client
        self._cache = cache
        self._now = now or (lambda: datetime.now(UTC))
        self._lock = RLock()
        self._refreshing = False
        self._state = self._load_initial_state()

    @property
    def is_refreshing(self) -> bool:
        with self._lock:
            return self._refreshing

    def get_state(self) -> PiForgeWeatherAlertState:
        """Return immutable already-published state without I/O."""
        with self._lock:
            return self._state

    def refresh(self) -> PiForgeWeatherAlertState:
        """Refresh alerts off-thread and persist before publication."""
        with self._lock:
            if self._refreshing:
                return self._state

            self._refreshing = True
            previous = self._state

        try:
            attempted_at = self._aware_now()

            try:
                result = self._client.fetch_alerts()
            except ForgeWeatherAlertClientTransportError as error:
                return self._publish_failure(
                    previous,
                    attempted_at=attempted_at,
                    error_kind=PiForgeWeatherAlertErrorKind.TRANSPORT,
                    error=error,
                )
            except ForgeWeatherAlertClientValidationError as error:
                return self._publish_failure(
                    previous,
                    attempted_at=attempted_at,
                    error_kind=PiForgeWeatherAlertErrorKind.VALIDATION,
                    error=error,
                )

            if result.snapshot is None:
                return self._publish_no_data(
                    previous,
                    result,
                    attempted_at=attempted_at,
                )

            try:
                self._cache.replace(result)
            except StorageError as error:
                return self._publish_failure(
                    previous,
                    attempted_at=attempted_at,
                    error_kind=PiForgeWeatherAlertErrorKind.STORAGE_WRITE,
                    error=error,
                )

            state = PiForgeWeatherAlertState(
                kind=PiForgeWeatherAlertStateKind.LIVE,
                snapshot_revision=result.revision,
                snapshot=result.snapshot,
                health=result.health,
                applicability=result.health.applicability,
                last_attempt_at=attempted_at,
                last_success_at=result.received_at,
            )
            return self._publish(state)
        finally:
            with self._lock:
                self._refreshing = False

    def _load_initial_state(
        self,
    ) -> PiForgeWeatherAlertState:
        try:
            result = self._cache.load()
        except StorageError as error:
            return PiForgeWeatherAlertState(
                kind=PiForgeWeatherAlertStateKind.NO_DATA,
                applicability=WeatherAlertApplicability.UNAVAILABLE,
                error_kind=(
                    PiForgeWeatherAlertErrorKind.STORAGE_READ
                ),
                last_error=self._bounded_error(error),
            )

        if result is None or result.snapshot is None:
            return PiForgeWeatherAlertState(
                kind=PiForgeWeatherAlertStateKind.NO_DATA,
                applicability=WeatherAlertApplicability.UNAVAILABLE,
            )

        # Restart never reasserts point applicability from disk.
        return PiForgeWeatherAlertState(
            kind=PiForgeWeatherAlertStateKind.RETAINED,
            snapshot_revision=result.revision,
            snapshot=result.snapshot,
            health=result.health,
            applicability=(
                WeatherAlertApplicability.RETAINED_UNVERIFIED
            ),
            last_success_at=result.received_at,
        )

    def _publish_no_data(
        self,
        previous: PiForgeWeatherAlertState,
        result: ForgeWeatherAlertClientResult,
        *,
        attempted_at: datetime,
    ) -> PiForgeWeatherAlertState:
        if previous.snapshot is None:
            return self._publish(
                PiForgeWeatherAlertState(
                    kind=PiForgeWeatherAlertStateKind.NO_DATA,
                    health=result.health,
                    applicability=(
                        WeatherAlertApplicability.UNAVAILABLE
                    ),
                    last_attempt_at=attempted_at,
                    last_success_at=result.received_at,
                )
            )

        return self._publish(
            self._retained_from_previous(
                previous,
                attempted_at=attempted_at,
                health=result.health,
            )
        )

    def _publish_failure(
        self,
        previous: PiForgeWeatherAlertState,
        *,
        attempted_at: datetime,
        error_kind: PiForgeWeatherAlertErrorKind,
        error: BaseException,
    ) -> PiForgeWeatherAlertState:
        if previous.snapshot is None:
            state = PiForgeWeatherAlertState(
                kind=PiForgeWeatherAlertStateKind.NO_DATA,
                health=previous.health,
                applicability=WeatherAlertApplicability.UNAVAILABLE,
                last_attempt_at=attempted_at,
                last_success_at=previous.last_success_at,
                error_kind=error_kind,
                last_error=self._bounded_error(error),
            )
        else:
            state = self._retained_from_previous(
                previous,
                attempted_at=attempted_at,
                health=previous.health,
                error_kind=error_kind,
                error=error,
            )

        return self._publish(state)

    def _retained_from_previous(
        self,
        previous: PiForgeWeatherAlertState,
        *,
        attempted_at: datetime,
        health: ForgeRemoteWeatherAlertHealth | None,
        error_kind: PiForgeWeatherAlertErrorKind | None = None,
        error: BaseException | None = None,
    ) -> PiForgeWeatherAlertState:
        assert previous.snapshot is not None
        assert previous.snapshot_revision is not None

        return PiForgeWeatherAlertState(
            kind=PiForgeWeatherAlertStateKind.RETAINED,
            snapshot_revision=previous.snapshot_revision,
            snapshot=previous.snapshot,
            health=health,
            applicability=(
                WeatherAlertApplicability.RETAINED_UNVERIFIED
            ),
            last_attempt_at=attempted_at,
            last_success_at=previous.last_success_at,
            error_kind=error_kind,
            last_error=(
                self._bounded_error(error)
                if error is not None
                else None
            ),
        )

    def _publish(
        self,
        state: PiForgeWeatherAlertState,
    ) -> PiForgeWeatherAlertState:
        with self._lock:
            self._state = state
            return self._state

    def _aware_now(self) -> datetime:
        value = self._now()

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(
                "Pi weather-alert clock must return an aware datetime"
            )

        return value.astimezone(UTC)

    @staticmethod
    def _bounded_error(error: BaseException) -> str:
        text = str(error).strip() or error.__class__.__name__
        return text[:_MAX_ERROR_LENGTH]
