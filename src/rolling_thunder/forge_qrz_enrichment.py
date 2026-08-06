"""Bounded best-effort QRZ enrichment for complete Forge provider slices."""

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock
from time import monotonic, sleep
from typing import Protocol

from pydantic import Field, ValidationError, field_validator

from rolling_thunder.domain import DomainModel
from rolling_thunder.forge_config import ForgeQrzEnrichmentConfig
from rolling_thunder.forge_spot_provider import ForgeProviderSlice
from rolling_thunder.qrz_xml import QrzCallsignProfile, normalize_qrz_callsign
from rolling_thunder.spot_domain import SpotRecord
from rolling_thunder.value_types import Callsign

_MAX_ERROR_LENGTH = 500
MonotonicClock = Callable[[], float]
Sleeper = Callable[[float], None]


class QrzProfileLookup(Protocol):
    """Small profile lookup boundary implemented by the QRZ XML adapter."""

    def lookup_profile(self, callsign: Callsign | str) -> QrzCallsignProfile | None:
        """Return one optional QRZ profile or raise a lookup-related exception."""
        ...


class ForgeQrzEnrichmentDiagnostics(DomainModel):
    """Immutable bounded diagnostics for one provider-slice enrichment attempt."""

    enabled: bool
    requested_callsigns: int = Field(ge=0)
    cache_hits: int = Field(ge=0)
    live_lookups: int = Field(ge=0)
    enriched_spots: int = Field(ge=0)
    budget_exhausted: bool = False
    last_error: str | None = Field(default=None, max_length=_MAX_ERROR_LENGTH)

    @field_validator("last_error")
    @classmethod
    def normalize_error(cls, value: str | None) -> str | None:
        """Trim and bound optional enrichment errors."""
        if value is None:
            return None
        normalized = value.strip()
        return normalized[:_MAX_ERROR_LENGTH] or None


class ForgeQrzEnrichmentResult(DomainModel):
    """Complete enriched provider slice plus immutable attempt diagnostics."""

    provider_slice: ForgeProviderSlice
    diagnostics: ForgeQrzEnrichmentDiagnostics


@dataclass(frozen=True, slots=True)
class _CacheEntry:
    profile: QrzCallsignProfile | None
    expires_at: float


class ForgeQrzEnricher:
    """Fill missing spot names and grids through bounded cached QRZ lookups."""

    def __init__(
        self,
        config: ForgeQrzEnrichmentConfig,
        lookup: QrzProfileLookup,
        *,
        clock: MonotonicClock | None = None,
        sleeper: Sleeper | None = None,
    ) -> None:
        self._config = config
        self._lookup = lookup
        self._clock = clock or monotonic
        self._sleep = sleeper or sleep
        self._cache: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._last_live_lookup_at: float | None = None
        self._lock = RLock()

    @property
    def cache_size(self) -> int:
        """Return the current bounded in-memory cache size."""
        with self._lock:
            return len(self._cache)

    def enrich_slice(self, provider_slice: ForgeProviderSlice) -> ForgeQrzEnrichmentResult:
        """Return a provider slice enriched without changing action-critical data."""
        with self._lock:
            if not self._config.enabled:
                return ForgeQrzEnrichmentResult(
                    provider_slice=provider_slice,
                    diagnostics=ForgeQrzEnrichmentDiagnostics(enabled=False),
                )

            requested = self._requested_callsigns(provider_slice)
            profiles: dict[str, QrzCallsignProfile | None] = {}
            cache_hits = 0
            live_lookups = 0
            budget_exhausted = False
            last_error: str | None = None

            for callsign in requested:
                now = self._clock()
                cache_hit, cached_profile = self._cache_lookup(callsign, now=now)
                if cache_hit:
                    cache_hits += 1
                    profiles[callsign] = cached_profile
                    continue

                if live_lookups >= self._config.max_lookups_per_refresh:
                    budget_exhausted = True
                    continue

                self._wait_for_live_lookup()
                try:
                    returned_profile = self._lookup.lookup_profile(callsign)
                except Exception as error:  # noqa: BLE001 - QRZ must not invalidate provider data
                    live_lookups += 1
                    self._last_live_lookup_at = self._clock()
                    last_error = self._bounded_error(error)
                    break

                live_lookups += 1
                completed_at = self._clock()
                self._last_live_lookup_at = completed_at

                profile, profile_error = self._validated_profile(
                    callsign,
                    returned_profile,
                )
                if profile_error is not None:
                    last_error = profile_error
                    break

                profiles[callsign] = profile
                self._cache_store(callsign, profile, now=completed_at)

            enriched_spots: list[SpotRecord] = []
            enriched_count = 0
            for spot in provider_slice.spots:
                callsign = normalize_qrz_callsign(spot.callsign)
                if callsign not in profiles or profiles[callsign] is None:
                    enriched_spots.append(spot)
                    continue

                profile = profiles[callsign]
                assert profile is not None
                operator_name = spot.operator_name or profile.name
                grid = spot.grid or profile.grid
                if operator_name == spot.operator_name and grid == spot.grid:
                    enriched_spots.append(spot)
                    continue

                try:
                    enriched = SpotRecord.model_validate(
                        {
                            **spot.model_dump(mode="python"),
                            "operator_name": operator_name,
                            "grid": grid,
                        }
                    )
                except ValidationError as error:
                    last_error = self._bounded_error(error)
                    enriched_spots.append(spot)
                    continue

                enriched_spots.append(enriched)
                enriched_count += 1

            enriched_slice = ForgeProviderSlice.from_spots(
                provider=provider_slice.provider,
                fetched_at=provider_slice.fetched_at,
                spots=enriched_spots,
            )
            return ForgeQrzEnrichmentResult(
                provider_slice=enriched_slice,
                diagnostics=ForgeQrzEnrichmentDiagnostics(
                    enabled=True,
                    requested_callsigns=len(requested),
                    cache_hits=cache_hits,
                    live_lookups=live_lookups,
                    enriched_spots=enriched_count,
                    budget_exhausted=budget_exhausted,
                    last_error=last_error,
                ),
            )

    @staticmethod
    def _requested_callsigns(provider_slice: ForgeProviderSlice) -> tuple[str, ...]:
        requested: dict[str, None] = {}
        for spot in provider_slice.spots:
            if spot.operator_name is not None and spot.grid is not None:
                continue
            requested.setdefault(normalize_qrz_callsign(spot.callsign), None)
        return tuple(requested)

    def _cache_lookup(
        self,
        callsign: str,
        *,
        now: float,
    ) -> tuple[bool, QrzCallsignProfile | None]:
        entry = self._cache.get(callsign)
        if entry is None:
            return False, None
        if entry.expires_at <= now:
            del self._cache[callsign]
            return False, None
        self._cache.move_to_end(callsign)
        return True, entry.profile

    def _cache_store(
        self,
        callsign: str,
        profile: QrzCallsignProfile | None,
        *,
        now: float,
    ) -> None:
        ttl = (
            self._config.positive_ttl_s
            if profile is not None
            else self._config.negative_ttl_s
        )
        self._cache[callsign] = _CacheEntry(
            profile=profile,
            expires_at=now + ttl,
        )
        self._cache.move_to_end(callsign)
        while len(self._cache) > self._config.max_cache_entries:
            self._cache.popitem(last=False)

    def _wait_for_live_lookup(self) -> None:
        if self._last_live_lookup_at is None:
            return
        elapsed = self._clock() - self._last_live_lookup_at
        delay = self._config.minimum_request_interval_s - elapsed
        if delay > 0:
            self._sleep(delay)

    @staticmethod
    def _validated_profile(
        callsign: str,
        profile: QrzCallsignProfile | None,
    ) -> tuple[QrzCallsignProfile | None, str | None]:
        if profile is None:
            return None, None
        if normalize_qrz_callsign(profile.callsign) != callsign:
            return None, "QRZ returned a profile for a different callsign."
        if profile.name is None and profile.grid is None:
            return None, None
        return profile, None

    @staticmethod
    def _bounded_error(error: BaseException) -> str:
        text = str(error).strip() or error.__class__.__name__
        return text[:_MAX_ERROR_LENGTH]
