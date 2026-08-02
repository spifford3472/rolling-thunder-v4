"""Background-only POTA callsign and park-detail enrichment."""

from collections.abc import Callable, Iterable
from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from threading import Lock
from typing import Generic, Protocol, TypeVar

from rolling_thunder.pota_spots import ParkReference
from rolling_thunder.qrz_xml import QrzCallsignProfile, QrzLookupError, normalize_qrz_callsign
from rolling_thunder.value_types import Callsign


class CallsignProfileProvider(Protocol):
    """Resolve a callsign to optional QRZ presentation metadata."""

    def lookup_profile(
        self,
        callsign: Callsign | str,
    ) -> QrzCallsignProfile | None:
        """Return QRZ profile metadata or none when unavailable."""
        ...


class CallsignPhotoProvider(Protocol):
    """Retrieve and normalize a QRZ-hosted primary profile image."""

    def fetch_photo(self, image_url: str) -> bytes:
        """Return a normalized PNG for one trusted QRZ image URL."""
        ...


class ParkWeatherProvider(Protocol):
    """Retrieve current weather and local time for one park."""

    def fetch_weather(self, park: ParkReference) -> "ParkWeather":
        """Return current park weather and local time."""
        ...


class StateOutlineProvider(Protocol):
    """Retrieve a generalized state outline for one POTA location code."""

    def fetch_outline(self, location_code: str | None) -> "StateOutline | None":
        """Return a state outline or none for unsupported locations."""
        ...


@dataclass(frozen=True)
class ParkWeather:
    """Current temperature, condition, and local time at a park."""

    temperature_c: float
    temperature_f: float
    local_time: str
    weather_code: int
    is_day: bool
    timezone: str | None = None


@dataclass(frozen=True)
class StateOutline:
    """Generalized state polygons in longitude/latitude coordinates."""

    state_code: str
    state_name: str
    rings: tuple[tuple[tuple[float, float], ...], ...]


@dataclass(frozen=True)
class CallsignProfileSnapshot:
    """Cached QRZ presentation data for one normalized callsign."""

    callsign: str
    name: str | None
    image_url: str | None
    photo_png: bytes | None = None
    photo_error: str | None = None


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
    outline: StateOutline | None = None
    weather_error: str | None = None
    map_error: str | None = None


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
        callsign_provider: CallsignProfileProvider | None = None,
        callsign_photo_provider: CallsignPhotoProvider | None = None,
        weather_provider: ParkWeatherProvider | None = None,
        state_outline_provider: StateOutlineProvider | None = None,
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
        self._callsign_photo_provider = callsign_photo_provider
        self._weather_provider = weather_provider
        self._state_outline_provider = state_outline_provider
        self._success_ttl = success_ttl
        self._negative_ttl = negative_ttl
        self._maximum_cache_entries = maximum_cache_entries
        self._clock = clock
        self._executor = executor
        self._owns_executor = executor is None
        self._started = False
        self._lock = Lock()
        self._pending_profiles: set[str] = set()
        self._pending_photos: set[str] = set()
        self._requested_photos: set[str] = set()
        self._pending_parks: set[str] = set()
        self._profile_cache: dict[
            str,
            _CacheEntry[CallsignProfileSnapshot | None],
        ] = {}
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
        """Stop accepting work and cancel queued tasks without blocking the UI."""
        if not self._started:
            return
        self._started = False
        executor = self._executor
        if executor is not None and self._owns_executor:
            executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None
        with self._lock:
            self._pending_profiles.clear()
            self._pending_photos.clear()
            self._requested_photos.clear()
            self._pending_parks.clear()

    def prefetch_callsigns(self, callsigns: Iterable[Callsign | str]) -> None:
        """Queue uncached QRZ profile metadata without downloading photos."""
        if not self._started or self._callsign_provider is None:
            return
        executor = self._executor
        if executor is None:
            return

        now = self._aware_now()
        to_submit: list[str] = []
        for callsign in callsigns:
            normalized = normalize_qrz_callsign(callsign)
            with self._lock:
                entry = self._profile_cache.get(normalized)
                if entry is not None and entry.expires_at > now:
                    continue
                if normalized in self._pending_profiles:
                    continue
                self._pending_profiles.add(normalized)
                to_submit.append(normalized)
        for normalized in to_submit:
            executor.submit(self._lookup_profile, normalized)

    def request_callsign_photo(
        self,
        callsign: Callsign | str,
    ) -> CallsignProfileSnapshot | None:
        """Request the selected operator photo without blocking the caller."""
        normalized = normalize_qrz_callsign(callsign)
        now = self._aware_now()
        executor = self._executor
        submit_profile = False
        submit_photo = False
        image_url: str | None = None

        with self._lock:
            self._requested_photos.add(normalized)
            entry = self._profile_cache.get(normalized)
            if entry is None or entry.expires_at <= now:
                if (
                    self._started
                    and self._callsign_provider is not None
                    and executor is not None
                    and normalized not in self._pending_profiles
                ):
                    self._pending_profiles.add(normalized)
                    submit_profile = True
                snapshot = None
            else:
                snapshot = entry.value
                if (
                    snapshot is not None
                    and snapshot.photo_png is None
                    and snapshot.photo_error is None
                    and snapshot.image_url is not None
                    and self._started
                    and self._callsign_photo_provider is not None
                    and executor is not None
                    and normalized not in self._pending_photos
                ):
                    self._pending_photos.add(normalized)
                    image_url = snapshot.image_url
                    submit_photo = True

        if submit_profile and executor is not None:
            executor.submit(self._lookup_profile, normalized)
        if submit_photo and executor is not None and image_url is not None:
            executor.submit(self._fetch_profile_photo, normalized, image_url)
        return snapshot

    def get_callsign_profile(
        self,
        callsign: Callsign | str,
    ) -> CallsignProfileSnapshot | None:
        """Return only cached QRZ profile data; never perform I/O."""
        normalized = normalize_qrz_callsign(callsign)
        now = self._aware_now()
        with self._lock:
            entry = self._profile_cache.get(normalized)
            if entry is None:
                return None
            if entry.expires_at <= now:
                del self._profile_cache[normalized]
                return None
            return entry.value

    def get_callsign_name(self, callsign: Callsign | str) -> str | None:
        """Return only a cached QRZ name; never perform I/O."""
        profile = self.get_callsign_profile(callsign)
        return profile.name if profile is not None else None

    def request_park_detail(self, park: ParkReference) -> ParkDetailSnapshot:
        """Return cached state or queue a non-blocking park-detail refresh."""
        park_name = park.name or park.reference
        now = self._aware_now()
        executor: Executor | None = None
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
                or (
                    self._weather_provider is None
                    and self._state_outline_provider is None
                )
                or self._executor is None
            ):
                unavailable = ParkDetailSnapshot(
                    park_reference=park.reference,
                    park_name=park_name,
                    status=ParkDetailStatus.UNAVAILABLE,
                    weather_error="Weather unavailable",
                    map_error="Map unavailable",
                )
                self._store_park_locked(unavailable, now, self._negative_ttl)
                return unavailable

            self._pending_parks.add(park.reference)
            executor = self._executor

        executor.submit(self._fetch_park_detail, park)
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

    def _lookup_profile(self, callsign: str) -> None:
        now = self._aware_now()
        snapshot: CallsignProfileSnapshot | None = None
        ttl = self._negative_ttl
        submit_photo = False
        image_url: str | None = None
        try:
            provider = self._callsign_provider
            if provider is not None:
                profile = provider.lookup_profile(callsign)
                if profile is not None:
                    snapshot = CallsignProfileSnapshot(
                        callsign=callsign,
                        name=profile.name,
                        image_url=profile.image_url,
                    )
                    ttl = self._success_ttl
        except QrzLookupError:
            snapshot = None
        finally:
            with self._lock:
                self._profile_cache[callsign] = _CacheEntry(
                    value=snapshot,
                    stored_at=now,
                    expires_at=now + ttl,
                )
                self._pending_profiles.discard(callsign)
                if (
                    snapshot is not None
                    and snapshot.image_url is not None
                    and callsign in self._requested_photos
                    and self._started
                    and self._callsign_photo_provider is not None
                    and self._executor is not None
                    and callsign not in self._pending_photos
                ):
                    self._pending_photos.add(callsign)
                    image_url = snapshot.image_url
                    submit_photo = True
                self._trim_cache_locked(self._profile_cache)

        if submit_photo and image_url is not None and self._executor is not None:
            self._executor.submit(self._fetch_profile_photo, callsign, image_url)

    def _fetch_profile_photo(self, callsign: str, image_url: str) -> None:
        now = self._aware_now()
        photo_png: bytes | None = None
        photo_error: str | None = None
        try:
            provider = self._callsign_photo_provider
            if provider is None:
                photo_error = "Photo unavailable"
            else:
                photo_png = provider.fetch_photo(image_url)
        except (OSError, TimeoutError, ValueError):
            photo_error = "Photo unavailable"

        with self._lock:
            entry = self._profile_cache.get(callsign)
            if entry is not None and entry.value is not None:
                updated = replace(
                    entry.value,
                    photo_png=photo_png,
                    photo_error=photo_error,
                )
                self._profile_cache[callsign] = _CacheEntry(
                    value=updated,
                    stored_at=now,
                    expires_at=now + self._success_ttl,
                )
            self._pending_photos.discard(callsign)
            self._trim_cache_locked(self._profile_cache)

    def _fetch_park_detail(self, park: ParkReference) -> None:
        park_name = park.name or park.reference
        weather: ParkWeather | None = None
        outline: StateOutline | None = None
        weather_error: str | None = None
        map_error: str | None = None

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
            if self._state_outline_provider is None:
                map_error = "Map unavailable"
            else:
                outline = self._state_outline_provider.fetch_outline(
                    park.location_code
                )
                if outline is None:
                    map_error = "Map unavailable"
        except (OSError, TimeoutError, ValueError):
            map_error = "Map unavailable"

        status = (
            ParkDetailStatus.READY
            if weather is not None or outline is not None
            else ParkDetailStatus.UNAVAILABLE
        )
        snapshot = ParkDetailSnapshot(
            park_reference=park.reference,
            park_name=park_name,
            status=status,
            weather=weather,
            outline=outline,
            weather_error=weather_error,
            map_error=map_error,
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

    def _trim_cache_locked(self, cache: dict[str, _CacheEntry[T]]) -> None:
        while len(cache) > self._maximum_cache_entries:
            oldest_key = min(cache, key=lambda key: cache[key].stored_at)
            del cache[oldest_key]

    def _aware_now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("POTA enrichment clock must be timezone-aware.")
        return now.astimezone(UTC)
