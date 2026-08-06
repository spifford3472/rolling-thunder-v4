"""Persistence-before-activation core for Forge spot aggregation."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from enum import StrEnum
from threading import RLock
from typing import Final

from pydantic import Field, ValidationError, field_validator, model_validator

from rolling_thunder.domain import DomainModel
from rolling_thunder.forge_snapshot_repository import (
    ForgeSnapshotRepository,
    ForgeSnapshotStorageError,
    ForgeStoredSnapshot,
)
from rolling_thunder.forge_spot_provider import (
    ForgeProviderSlice,
    ForgeSpotProvider,
    ForgeSpotProviderError,
)
from rolling_thunder.spot_domain import SpotProvider, SpotSnapshot

_MAX_ERROR_LENGTH: Final = 500
Clock = Callable[[], datetime]


class ForgeProviderHealthStatus(StrEnum):
    """Operational state of one configured Forge spot provider."""

    STARTING = "starting"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class ForgeProviderHealth(DomainModel):
    """Immutable published health for one provider family."""

    provider: SpotProvider
    status: ForgeProviderHealthStatus
    active_spot_count: int = Field(ge=0)
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = Field(default=None, max_length=_MAX_ERROR_LENGTH)

    @field_validator("last_attempt_at", "last_success_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime | None) -> datetime | None:
        """Require aware provider timestamps and normalize them to UTC."""
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("provider health timestamps must include timezone information")
        return value.astimezone(UTC)

    @field_validator("last_error")
    @classmethod
    def normalize_error(cls, value: str | None) -> str | None:
        """Trim and bound optional provider errors."""
        if value is None:
            return None
        normalized = value.strip()
        return normalized[:_MAX_ERROR_LENGTH] or None

    @model_validator(mode="after")
    def validate_consistency(self) -> ForgeProviderHealth:
        """Keep published status, timestamps, and errors internally consistent."""
        if self.status is ForgeProviderHealthStatus.STARTING:
            if self.last_attempt_at is not None or self.last_error is not None:
                raise ValueError("starting provider health cannot contain attempt data")
        elif self.status is ForgeProviderHealthStatus.HEALTHY:
            if self.last_attempt_at is None or self.last_success_at is None:
                raise ValueError("healthy provider health requires attempt and success times")
            if self.last_error is not None:
                raise ValueError("healthy provider health cannot contain an error")
        elif self.status is ForgeProviderHealthStatus.DEGRADED:
            if self.last_success_at is None or self.last_error is None:
                raise ValueError("degraded provider health requires retained success and error data")
        elif self.last_attempt_at is None or self.last_error is None:
            raise ValueError("unavailable provider health requires attempt and error data")
        return self


class ForgeAggregationState(DomainModel):
    """Complete immutable state published to future REST handlers."""

    revision: int = Field(ge=0)
    snapshot: SpotSnapshot
    providers: tuple[ForgeProviderHealth, ...]
    startup_storage_error: str | None = Field(default=None, max_length=_MAX_ERROR_LENGTH)
    persistence_error: str | None = Field(default=None, max_length=_MAX_ERROR_LENGTH)

    @field_validator("providers")
    @classmethod
    def normalize_providers(
        cls,
        value: tuple[ForgeProviderHealth, ...],
    ) -> tuple[ForgeProviderHealth, ...]:
        """Publish deterministic provider order and reject duplicates."""
        ordered = tuple(sorted(value, key=lambda item: item.provider.value))
        provider_ids = [item.provider for item in ordered]
        if len(provider_ids) != len(set(provider_ids)):
            raise ValueError("aggregation state providers must be unique")
        return ordered

    @field_validator("startup_storage_error", "persistence_error")
    @classmethod
    def normalize_service_error(cls, value: str | None) -> str | None:
        """Trim and bound optional service-level storage errors."""
        if value is None:
            return None
        normalized = value.strip()
        return normalized[:_MAX_ERROR_LENGTH] or None


class ForgeSpotAggregationService:
    """Refresh provider slices and publish only successfully persisted snapshots."""

    def __init__(
        self,
        providers: Iterable[ForgeSpotProvider],
        repository: ForgeSnapshotRepository,
        *,
        now: Clock | None = None,
    ) -> None:
        provider_map: dict[SpotProvider, ForgeSpotProvider] = {}
        for provider in providers:
            if provider.provider in provider_map:
                raise ValueError(f"duplicate Forge spot provider: {provider.provider.value}")
            provider_map[provider.provider] = provider
        if not provider_map:
            raise ValueError("at least one Forge spot provider must be configured")

        self._providers = provider_map
        self._repository = repository
        self._now = now or (lambda: datetime.now(UTC))
        self._lock = RLock()
        self._refreshing = False
        self._active_slices: dict[SpotProvider, ForgeProviderSlice] = {}
        self._provider_health: dict[SpotProvider, ForgeProviderHealth] = {
            provider: self._starting_health(provider) for provider in provider_map
        }
        self._startup_storage_error: str | None = None
        self._persistence_error: str | None = None

        try:
            stored = repository.load()
        except ForgeSnapshotStorageError as error:
            stored = None
            self._startup_storage_error = self._bounded_error(error)

        if stored is None:
            snapshot = SpotSnapshot.empty(generated_at=self._aware_now())
            revision = 0
        else:
            snapshot = stored.snapshot
            revision = stored.revision
            self._restore_slices(stored)

        self._state = self._build_state(revision=revision, snapshot=snapshot)

    @property
    def is_refreshing(self) -> bool:
        """Return whether one provider refresh is currently executing."""
        with self._lock:
            return self._refreshing

    def get_state(self) -> ForgeAggregationState:
        """Return the currently published immutable state without external work."""
        with self._lock:
            return self._state

    def refresh_provider(self, provider: SpotProvider) -> ForgeAggregationState:
        """Refresh one provider and activate only after durable persistence."""
        with self._lock:
            if self._refreshing:
                return self._state
            adapter = self._providers.get(provider)
            if adapter is None:
                raise ValueError(f"Forge spot provider is not configured: {provider.value}")
            self._refreshing = True
            previous_slices = dict(self._active_slices)
            previous_health = dict(self._provider_health)
            previous_state = self._state

        try:
            attempted_at = self._aware_now()
        except ValueError:
            with self._lock:
                self._refreshing = False
            raise

        try:
            provider_slice = adapter.fetch_slice()
            if provider_slice.provider is not provider:
                raise ValueError(
                    "Forge provider returned a slice for another provider family"
                )

            candidate_slices = dict(previous_slices)
            candidate_slices[provider] = provider_slice
            generated_at = self._aware_now()
            candidate_snapshot = SpotSnapshot.from_spots(
                generated_at=generated_at,
                spots=(
                    spot
                    for candidate_slice in candidate_slices.values()
                    for spot in candidate_slice.spots
                ),
            )
            stored = self._repository.replace(
                candidate_snapshot,
                self._ordered_slices(candidate_slices),
            )

            with self._lock:
                self._active_slices = {
                    item.provider: item for item in stored.provider_slices
                }
                self._provider_health = previous_health
                self._provider_health[provider] = ForgeProviderHealth(
                    provider=provider,
                    status=ForgeProviderHealthStatus.HEALTHY,
                    active_spot_count=len(provider_slice.spots),
                    last_attempt_at=attempted_at,
                    last_success_at=provider_slice.fetched_at,
                )
                self._startup_storage_error = None
                self._persistence_error = None
                self._state = self._build_state(
                    revision=stored.revision,
                    snapshot=stored.snapshot,
                )
                return self._state
        except ForgeSnapshotStorageError as error:
            return self._publish_failure(
                provider=provider,
                attempted_at=attempted_at,
                error=error,
                previous_slices=previous_slices,
                previous_health=previous_health,
                previous_state=previous_state,
                persistence_error=self._bounded_error(error),
            )
        except (ForgeSpotProviderError, ValidationError, ValueError) as error:
            return self._publish_failure(
                provider=provider,
                attempted_at=attempted_at,
                error=error,
                previous_slices=previous_slices,
                previous_health=previous_health,
                previous_state=previous_state,
                persistence_error=self._persistence_error,
            )
        finally:
            with self._lock:
                self._refreshing = False

    def refresh_all(self) -> ForgeAggregationState:
        """Refresh every configured provider in deterministic provider order."""
        state = self.get_state()
        for provider in sorted(self._providers, key=lambda item: item.value):
            state = self.refresh_provider(provider)
        return state

    def _restore_slices(self, stored: ForgeStoredSnapshot) -> None:
        self._active_slices = {
            provider_slice.provider: provider_slice
            for provider_slice in stored.provider_slices
        }
        for provider in set(self._providers) | set(self._active_slices):
            provider_slice = self._active_slices.get(provider)
            if provider_slice is None:
                self._provider_health[provider] = self._starting_health(provider)
            else:
                self._provider_health[provider] = ForgeProviderHealth(
                    provider=provider,
                    status=ForgeProviderHealthStatus.DEGRADED,
                    active_spot_count=len(provider_slice.spots),
                    last_success_at=provider_slice.fetched_at,
                    last_error="Using retained Forge snapshot until a live refresh succeeds.",
                )

    def _publish_failure(
        self,
        *,
        provider: SpotProvider,
        attempted_at: datetime,
        error: BaseException,
        previous_slices: dict[SpotProvider, ForgeProviderSlice],
        previous_health: dict[SpotProvider, ForgeProviderHealth],
        previous_state: ForgeAggregationState,
        persistence_error: str | None,
    ) -> ForgeAggregationState:
        active_slice = previous_slices.get(provider)
        previous_health[provider] = ForgeProviderHealth(
            provider=provider,
            status=(
                ForgeProviderHealthStatus.DEGRADED
                if active_slice is not None
                else ForgeProviderHealthStatus.UNAVAILABLE
            ),
            active_spot_count=len(active_slice.spots) if active_slice is not None else 0,
            last_attempt_at=attempted_at,
            last_success_at=(active_slice.fetched_at if active_slice is not None else None),
            last_error=self._bounded_error(error),
        )
        with self._lock:
            self._active_slices = previous_slices
            self._provider_health = previous_health
            self._persistence_error = persistence_error
            self._state = self._build_state(
                revision=previous_state.revision,
                snapshot=previous_state.snapshot,
            )
            return self._state

    def _build_state(
        self,
        *,
        revision: int,
        snapshot: SpotSnapshot,
    ) -> ForgeAggregationState:
        return ForgeAggregationState(
            revision=revision,
            snapshot=snapshot,
            providers=tuple(self._provider_health.values()),
            startup_storage_error=self._startup_storage_error,
            persistence_error=self._persistence_error,
        )

    @staticmethod
    def _ordered_slices(
        slices: dict[SpotProvider, ForgeProviderSlice],
    ) -> tuple[ForgeProviderSlice, ...]:
        return tuple(sorted(slices.values(), key=lambda item: item.provider.value))

    @staticmethod
    def _starting_health(provider: SpotProvider) -> ForgeProviderHealth:
        return ForgeProviderHealth(
            provider=provider,
            status=ForgeProviderHealthStatus.STARTING,
            active_spot_count=0,
        )

    def _aware_now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Forge aggregation clock must return an aware datetime")
        return value.astimezone(UTC)

    @staticmethod
    def _bounded_error(error: BaseException) -> str:
        text = str(error).strip() or error.__class__.__name__
        return text[:_MAX_ERROR_LENGTH]
