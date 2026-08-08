"""Thread-safe Pi service for durable Forge shared-spot state."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from threading import RLock
from typing import Protocol

from pydantic import Field, field_validator, model_validator

from rolling_thunder.domain import DomainModel
from rolling_thunder.forge_client import (
    ForgeClientError,
    ForgeRemoteProviderHealth,
    ForgeSpotClientResult,
)
from rolling_thunder.spot_domain import SpotSnapshot
from rolling_thunder.storage import StorageError

_MAX_ERROR_LENGTH = 500
Clock = Callable[[], datetime]


class ForgeSpotClient(Protocol):
    """Complete Forge snapshot client consumed by the Pi service."""

    def fetch_spots(self) -> ForgeSpotClientResult:
        """Fetch one complete validated Forge result."""
        ...


class ForgeSpotCache(Protocol):
    """Durable complete-snapshot boundary consumed by the Pi service."""

    def load(self) -> ForgeSpotClientResult | None:
        """Load the latest complete cached Forge result, if present."""
        ...

    def replace(self, result: ForgeSpotClientResult) -> None:
        """Transactionally replace the complete cached Forge result."""
        ...


class PiForgeSpotStateKind(StrEnum):
    """Origin/freshness state of the currently published Pi snapshot."""

    EMPTY = "empty"
    CACHED = "cached"
    LIVE = "live"
    RETAINED = "retained"


class PiForgeSpotErrorKind(StrEnum):
    """Bounded failure categories visible to diagnostics and future UI."""

    CACHE_READ = "cache_read"
    CLIENT = "client"
    CACHE_WRITE = "cache_write"


class PiForgeSpotState(DomainModel):
    """Immutable application-facing state for Forge-derived shared spots."""

    kind: PiForgeSpotStateKind
    snapshot_revision: int | None = Field(default=None, ge=0)
    snapshot: SpotSnapshot | None = None
    providers: tuple[ForgeRemoteProviderHealth, ...] = ()
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    error_kind: PiForgeSpotErrorKind | None = None
    last_error: str | None = Field(default=None, max_length=_MAX_ERROR_LENGTH)

    @field_validator("last_attempt_at", "last_success_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Pi Forge service timestamps must include timezone information")
        return value.astimezone(UTC)

    @field_validator("last_error")
    @classmethod
    def normalize_error(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized[:_MAX_ERROR_LENGTH] or None

    @model_validator(mode="after")
    def validate_consistency(self) -> PiForgeSpotState:
        has_snapshot = self.snapshot is not None
        if has_snapshot != (self.snapshot_revision is not None):
            raise ValueError("snapshot and revision must either both be present or both be absent")

        if not has_snapshot:
            if self.providers:
                raise ValueError("snapshot-less Pi Forge state cannot contain provider health")
            if self.last_success_at is not None:
                raise ValueError("snapshot-less Pi Forge state cannot contain a success timestamp")
        else:
            if self.last_success_at is None:
                raise ValueError("published Pi Forge snapshots require a success timestamp")
            if not self.providers:
                raise ValueError("published Pi Forge snapshots require provider health")

        if self.kind is PiForgeSpotStateKind.EMPTY and has_snapshot:
            raise ValueError("empty Pi Forge state cannot contain a snapshot")
        if self.kind is not PiForgeSpotStateKind.EMPTY and not has_snapshot:
            raise ValueError("non-empty Pi Forge state requires a snapshot")

        if self.kind in {PiForgeSpotStateKind.EMPTY, PiForgeSpotStateKind.CACHED}:
            if self.last_attempt_at is not None:
                raise ValueError("startup Pi Forge state cannot contain a live attempt timestamp")

        if self.kind is PiForgeSpotStateKind.LIVE:
            if self.last_attempt_at is None:
                raise ValueError("live Pi Forge state requires a live attempt timestamp")
            if self.error_kind is not None or self.last_error is not None:
                raise ValueError("live Pi Forge state cannot contain an error")

        if self.kind is PiForgeSpotStateKind.RETAINED and self.last_attempt_at is None:
            raise ValueError("retained Pi Forge state requires a failed live attempt timestamp")

        if (self.error_kind is None) != (self.last_error is None):
            raise ValueError("Pi Forge error kind and error text must be present together")

        return self

    @property
    def active_spot_count(self) -> int:
        """Return the number of currently usable shared spots."""
        return len(self.snapshot.spots) if self.snapshot is not None else 0

    @property
    def generated_at(self) -> datetime | None:
        """Return the original Forge generation time without resetting its age."""
        return self.snapshot.generated_at if self.snapshot is not None else None

    @property
    def has_usable_snapshot(self) -> bool:
        """Return whether callers may safely consume the retained snapshot."""
        return self.snapshot is not None


class PiForgeSpotService:
    """Publish only complete Forge snapshots that have been durably persisted."""

    def __init__(
        self,
        client: ForgeSpotClient,
        cache: ForgeSpotCache,
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
        """Return whether one refresh is currently executing."""
        with self._lock:
            return self._refreshing

    def get_state(self) -> PiForgeSpotState:
        """Return the latest immutable state without I/O."""
        with self._lock:
            return self._state

    def refresh(self) -> PiForgeSpotState:
        """Fetch, persist, then atomically publish one complete Forge snapshot."""
        with self._lock:
            if self._refreshing:
                return self._state
            self._refreshing = True
            previous_state = self._state

        attempted_at = self._aware_now()
        try:
            result = self._client.fetch_spots()
            self._cache.replace(result)
        except ForgeClientError as error:
            return self._publish_failure(
                previous_state,
                attempted_at=attempted_at,
                error_kind=PiForgeSpotErrorKind.CLIENT,
                error=error,
            )
        except StorageError as error:
            return self._publish_failure(
                previous_state,
                attempted_at=attempted_at,
                error_kind=PiForgeSpotErrorKind.CACHE_WRITE,
                error=error,
            )
        finally:
            with self._lock:
                self._refreshing = False

        state = self._state_from_result(
            result,
            kind=PiForgeSpotStateKind.LIVE,
            last_attempt_at=attempted_at,
        )
        with self._lock:
            self._state = state
            return self._state

    def _load_initial_state(self) -> PiForgeSpotState:
        try:
            result = self._cache.load()
        except StorageError as error:
            return PiForgeSpotState(
                kind=PiForgeSpotStateKind.EMPTY,
                error_kind=PiForgeSpotErrorKind.CACHE_READ,
                last_error=self._bounded_error(error),
            )

        if result is None:
            return PiForgeSpotState(kind=PiForgeSpotStateKind.EMPTY)

        return self._state_from_result(
            result,
            kind=PiForgeSpotStateKind.CACHED,
            last_attempt_at=None,
        )

    def _publish_failure(
        self,
        previous_state: PiForgeSpotState,
        *,
        attempted_at: datetime,
        error_kind: PiForgeSpotErrorKind,
        error: BaseException,
    ) -> PiForgeSpotState:
        if previous_state.snapshot is None:
            state = PiForgeSpotState(
                kind=PiForgeSpotStateKind.EMPTY,
                last_attempt_at=attempted_at,
                error_kind=error_kind,
                last_error=self._bounded_error(error),
            )
        else:
            state = PiForgeSpotState(
                kind=PiForgeSpotStateKind.RETAINED,
                snapshot_revision=previous_state.snapshot_revision,
                snapshot=previous_state.snapshot,
                providers=previous_state.providers,
                last_attempt_at=attempted_at,
                last_success_at=previous_state.last_success_at,
                error_kind=error_kind,
                last_error=self._bounded_error(error),
            )

        with self._lock:
            self._state = state
            return self._state

    @staticmethod
    def _state_from_result(
        result: ForgeSpotClientResult,
        *,
        kind: PiForgeSpotStateKind,
        last_attempt_at: datetime | None,
    ) -> PiForgeSpotState:
        return PiForgeSpotState(
            kind=kind,
            snapshot_revision=result.snapshot_revision,
            snapshot=result.snapshot,
            providers=result.providers,
            last_attempt_at=last_attempt_at,
            last_success_at=result.received_at,
        )

    def _aware_now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Pi Forge spot service clock must return an aware datetime")
        return value.astimezone(UTC)

    @staticmethod
    def _bounded_error(error: BaseException) -> str:
        text = str(error).strip() or error.__class__.__name__
        return text[:_MAX_ERROR_LENGTH]
