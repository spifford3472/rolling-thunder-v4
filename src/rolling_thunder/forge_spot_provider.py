"""Provider-neutral Forge boundary for complete immutable spot slices."""

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Protocol

from pydantic import field_validator, model_validator

from rolling_thunder.domain import DomainModel
from rolling_thunder.spot_domain import (
    SpotProvider,
    SpotRecord,
    canonicalize_spots,
)


class ForgeSpotProviderError(Exception):
    """Base exception for Forge spot-provider failures."""


class ForgeSpotProviderConnectionError(ForgeSpotProviderError):
    """Raised when a configured provider cannot be reached."""


class ForgeSpotProviderResponseError(ForgeSpotProviderError):
    """Raised when a provider returns an unusable response."""


class ForgeSpotProviderNormalizationError(ForgeSpotProviderError):
    """Raised when provider records cannot form a valid shared slice."""


class ForgeProviderSlice(DomainModel):
    """One complete canonical immutable slice returned by a Forge provider."""

    provider: SpotProvider
    fetched_at: datetime
    spots: tuple[SpotRecord, ...] = ()

    @field_validator("fetched_at")
    @classmethod
    def normalize_fetched_at(cls, value: datetime) -> datetime:
        """Require an aware fetch timestamp and normalize it to UTC."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("fetched_at must include timezone information")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_provider_slice(self) -> "ForgeProviderSlice":
        """Require one provider and canonical duplicate-free ordering."""
        if any(spot.provider is not self.provider for spot in self.spots):
            raise ValueError("provider slice contains a spot from another provider")
        if canonicalize_spots(self.spots) != self.spots:
            raise ValueError("provider slice spots must be canonical and duplicate-free")
        return self

    @classmethod
    def from_spots(
        cls,
        *,
        provider: SpotProvider,
        fetched_at: datetime,
        spots: Iterable[SpotRecord],
    ) -> "ForgeProviderSlice":
        """Canonicalize arbitrary provider input into one complete slice."""
        return cls(
            provider=provider,
            fetched_at=fetched_at,
            spots=canonicalize_spots(spots),
        )


class ForgeSpotProvider(Protocol):
    """Synchronous provider boundary consumed only by the Forge refresh core."""

    @property
    def provider(self) -> SpotProvider:
        """Return the shared provider family supplied by this adapter."""
        ...

    def fetch_slice(self) -> ForgeProviderSlice:
        """Fetch one complete immutable provider slice."""
        ...


class MockForgeSpotProvider:
    """Deterministic in-memory Forge provider for tests and development."""

    def __init__(
        self,
        provider_slice: ForgeProviderSlice,
        *,
        error: ForgeSpotProviderError | None = None,
    ) -> None:
        self._provider_slice = provider_slice
        self._error = error
        self.fetch_count = 0

    @property
    def provider(self) -> SpotProvider:
        """Return the configured provider family."""
        return self._provider_slice.provider

    def set_slice(self, provider_slice: ForgeProviderSlice) -> None:
        """Replace the deterministic result and clear any configured error."""
        if provider_slice.provider is not self.provider:
            raise ValueError("replacement slice must use the same provider")
        self._provider_slice = provider_slice
        self._error = None

    def set_error(self, error: ForgeSpotProviderError) -> None:
        """Configure a typed provider error for subsequent fetches."""
        self._error = error

    def fetch_slice(self) -> ForgeProviderSlice:
        """Return the configured slice or raise the configured typed error."""
        self.fetch_count += 1
        if self._error is not None:
            raise self._error
        return self._provider_slice
