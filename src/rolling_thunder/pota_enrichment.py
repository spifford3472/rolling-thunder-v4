"""Background-only POTA callsign and park-detail enrichment."""

from collections.abc import Callable, Iterable
from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from threading import Lock
from typing import Protocol, TypeVar, Generic

from rolling_thunder.pota_spots import ParkReference
from rolling_thunder.qrz_xml import QrzLookupError, normalize_qrz_callsign
from rolling_thunder.value_types import Callsign


class CallsignNameProvider(Protocol):
    """Resolve a callsign to a human-readable operator name."""

    def lookup_name(self, callsign: Callsign | str) -> str | None:
        """Return a display name or none when no name is available."""
        ...


class ParkWeatherProvider(Protocol):
    """Retrieve current weather and local time for one park."""

    def fetch_weather(self, park: ParkReference) -> "ParkWeather":
        """Return current park weather and local time."""
        ...


class ParkImageProvider(Protocol):
    """Retrieve one licensed display image for a park."""

    def fetch_image(self, park: ParkReference) -> "ParkImage | None":
        """Return a normalized PNG image or none when none is available."""
        ...


@dataclass(frozen=True)
class ParkWeather:
    """Current temperature and local time at a park."""

    temperature_c: float
    temperature_f: float
    local_time: str
    timezone: str | None = None


@dataclass(frozen=True)
class ParkImage:
    """Licensed park image normalized for safe UI display."""

    png_bytes: bytes
    attribution: str
    license_name: str
    source_url: str


class ParkDetailStatus(StrEnum):
    """Availability state for one requested park-detail snapshot."""

    LOADING = "loading"
    READY = "ready"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class ParkDetailSnapshot:
    """Immutable background enrichment state for one park."""

    park_reference: str
    park_name: str
    status: ParkDetailStatus
    weather: ParkWeather | None = None
    image: ParkImage | None = None
    weather_error: str | None = None
    image_error: str | None = None


T = TypeVar("T")


@dataclass(frozen=True)
class _CacheEntry(Generic[T]):
    value: T
    stored_at: datetime
    expires_at: datetime


def _utc_now() -> datetime:
    return datetime.now(UTC)


class PotaEnrichmentService:
    """Own bounded background enrichment work and immutable cache snapshots."""

    def __init__(
        self,
        *,
        callsign_provider: CallsignNameProvider | None = None,
        weather_provider: ParkWeatherProvider | None = None,
        image_provider: ParkImageProvider | None = None,
        success_ttl: timedelta = timedelta(hours=24),
        negative_ttl: timedelta = timedelta(hours=1),
        maximum_cache_entries: int = 512,
        clock: Callable[[], datetime] = _utc_now,
        executor: Executor | None = None,
    ) -> None:
        if success_ttl <= timedelta(0):
            raise ValueError("POTA enrichment success TTL must be positive.")
        if negative_ttl <= timedelta(0):
            raise ValueError("POTA enrichment negative TTL must be positive.")
        if maximum_cache_entries < 1:
            raise ValueError("POTA enrichment cache size must be positive.")

        self._callsign_provider = callsign_provider
        self._weather_provider = weather_provider
        self._image_provider = image_provider
        self._success_ttl = success_ttl
        self._negative_ttl = negative_ttl
        self._maximum_cache_entries = maximum_cache_entries
        self._clock = clock
        self._executor = executor
        self._owns_executor = executor is None
        self._started = False
        self._lock = Lock()
        self._pending_callsigns: set[str] = set()
        self._pending_parks: set[str] = set()
        self._name_cache: dict[str, _CacheEntry[str | None]] = {}
        self._park_cache: dict[str, _CacheEntry[ParkDetailSnapshot]] = {}

    @property
    def is_running(self) -> bool:
        """Return whether background work may be submitted."""
        return self._started

    def start(self) -> None:
        """Start the bounded background executor."""
        if self._started:
            raise RuntimeError("POTA enrichment service is already running.")
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=3,
                thread_name_prefix="rolling-thunder-pota-enrichment",
            )
        self._started = True

    def stop(self) -> None:
        """Stop accepting work and cancel queued tasks during application shutdown."""
        if not self._started:
            return
        self._started = False
        executor = self._executor
        if executor is not None and self._owns_executor:
            executor.shutdown(wait=True, cancel_futures=True)
            self._executor = None
        with self._lock:
            self._pending_callsigns.clear()
            self._pending_parks.clear()

    def prefetch_callsigns(self, callsigns: Iterable[Callsign | str]) -> None:
        """Queue uncached QRZ lookups without waiting for network work."""
        if not self._started or self._callsign_provider is None:
            return
        executor = self._executor
        if executor is None:
            return

        now = self._aware_now()
        for callsign in callsigns:
            normalized = normalize_qrz_callsign(callsign)
            with self._lock:
                if self._cache_value(self._name_cache, normalized, now) is not None:
                    continue
                entry = self._name_cache.get(normalized)
                if entry is not None and entry.expires_at > now:
                    continue
                if normalized in self._pending_callsigns:
                    continue
                self._pending_callsigns.add(normalized)
            executor.submit(self._lookup_callsign, normalized)

    def get_callsign_name(self, callsign: Callsign | str) -> str | None:
        """Return only a cached name; never perform I/O for the caller."""
        normalized = normalize_qrz_callsign(callsign)
        now = self._aware_now()
        with self._lock:
            entry = self._name_cache.get(normalized)
            if entry is None:
                return None
            if entry.expires_at <= now:
                del self._name_cache[normalized]
                return None
            return entry.value

    def request_park_detail(self, park: ParkReference) -> ParkDetailSnapshot:
        """Return cached state or queue a non-blocking park-detail refresh."""
        park_name = park.name or park.reference
        now = self._aware_now()
        with self._lock:
            entry = self._park_cache.get(park.reference)
            if entry is not None and entry.expires_at > now:
                return entry.value
            if park.reference in self._pending_parks:
                return ParkDetailSnapshot(
                    park_reference=park.reference,
                    park_name=park_name,
                    status=ParkDetailStatus.LOADING,
                )

            if (
                not self._started
                or (self._weather_provider is None and self._image_provider is None)
                or self._executor is None
            ):
                unavailable = ParkDetailSnapshot(
                    park_reference=park.reference,
                    park_name=park_name,
                    status=ParkDetailStatus.UNAVAILABLE,
                    weather_error="Weather unavailable",
                    image_error="Image unavailable",
                )
                self._store_park_locked(unavailable, now, self._negative_ttl)
                return unavailable

            self._pending_parks.add(park.reference)
            self._executor.submit(self._fetch_park_detail, park)
            return ParkDetailSnapshot(
                park_reference=park.reference,
                park_name=park_name,
                status=ParkDetailStatus.LOADING,
            )

    def get_park_detail(self, park_reference: str) -> ParkDetailSnapshot | None:
        """Return only a cached park snapshot; never perform I/O."""
        now = self._aware_now()
        with self._lock:
            entry = self._park_cache.get(park_reference)
            if entry is None:
                return None
            if entry.expires_at <= now:
                del self._park_cache[park_reference]
                return None
            return entry.value

    def _lookup_callsign(self, callsign: str) -> None:
        now = self._aware_now()
        name: str | None = None
        ttl = self._negative_ttl
        try:
            provider = self._callsign_provider
            if provider is not None:
                name = provider.lookup_name(callsign)
                if name is not None:
                    ttl = self._success_ttl
        except QrzLookupError:
            name = None
        finally:
            with self._lock:
                self._name_cache[callsign] = _CacheEntry(
                    value=name,
                    stored_at=now,
                    expires_at=now + ttl,
                )
                self._pending_callsigns.discard(callsign)
                self._trim_cache_locked(self._name_cache)

    def _fetch_park_detail(self, park: ParkReference) -> None:
        park_name = park.name or park.reference
        weather: ParkWeather | None = None
        image: ParkImage | None = None
        weather_error: str | None = None
        image_error: str | None = None

        try:
            if self._weather_provider is None:
                weather_error = "Weather unavailable"
            elif park.latitude is None or park.longitude is None:
                weather_error = "Coordinates unavailable"
            else:
                weather = self._weather_provider.fetch_weather(park)
        except (OSError, TimeoutError, ValueError):
            weather_error = "Weather unavailable"

        try:
            if self._image_provider is None:
                image_error = "Image unavailable"
            else:
                image = self._image_provider.fetch_image(park)
                if image is None:
                    image_error = "Image unavailable"
        except (OSError, TimeoutError, ValueError):
            image_error = "Image unavailable"

        status = (
            ParkDetailStatus.READY
            if weather is not None or image is not None
            else ParkDetailStatus.UNAVAILABLE
        )
        snapshot = ParkDetailSnapshot(
            park_reference=park.reference,
            park_name=park_name,
            status=status,
            weather=weather,
            image=image,
            weather_error=weather_error,
            image_error=image_error,
        )
        now = self._aware_now()
        ttl = self._success_ttl if status is ParkDetailStatus.READY else self._negative_ttl
        with self._lock:
            self._store_park_locked(snapshot, now, ttl)
            self._pending_parks.discard(park.reference)

    def _store_park_locked(
        self,
        snapshot: ParkDetailSnapshot,
        now: datetime,
        ttl: timedelta,
    ) -> None:
        self._park_cache[snapshot.park_reference] = _CacheEntry(
            value=snapshot,
            stored_at=now,
            expires_at=now + ttl,
        )
        self._trim_cache_locked(self._park_cache)

    @staticmethod
    def _cache_value(
        cache: dict[str, _CacheEntry[T]],
        key: str,
        now: datetime,
    ) -> T | None:
        entry = cache.get(key)
        if entry is None or entry.expires_at <= now:
            return None
        return entry.value

    def _trim_cache_locked(self, cache: dict[str, _CacheEntry[object]]) -> None:
        while len(cache) > self._maximum_cache_entries:
            oldest_key = min(cache, key=lambda key: cache[key].stored_at)
            del cache[oldest_key]

    def _aware_now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("POTA enrichment clock must be timezone-aware.")
        return now.astimezone(UTC)
