"""Forge-side callsign intelligence aggregation with bounded caches."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import RLock
from time import monotonic
from typing import Literal, Protocol

from rolling_thunder.callsign_info import (
    CallsignInfoLastQso,
    CallsignInfoProfile,
    CallsignInfoResponse,
    CallsignInfoWeather,
)
from rolling_thunder.contact_weather import weather_observation_from_snapshot
from rolling_thunder.forge_mobile_location import MobileLocationRecord
from rolling_thunder.forge_weather import (
    ForgeWeatherProviderError,
    WeatherConditionToken,
    WeatherSnapshot,
)
from rolling_thunder.maidenhead import maidenhead_grid_center
from rolling_thunder.qrz_xml import QrzCallsignProfile, normalize_qrz_callsign
from rolling_thunder.wavelog import WavelogQsoSummary, WavelogStationLocation

MonotonicClock = Callable[[], float]
UtcClock = Callable[[], datetime]


class QrzProfileLookup(Protocol):
    def lookup_profile(self, callsign: str) -> QrzCallsignProfile | None:
        """Return one normalized QRZ profile."""


class WavelogHistoryLookup(Protocol):
    def latest_qso(self, callsign: str) -> WavelogQsoSummary | None:
        """Return the newest exact-callsign QSO."""

    def list_station_locations(self) -> tuple[WavelogStationLocation, ...]:
        """Return station-location identities used by historical QSOs."""


class CallsignWeatherProvider(Protocol):
    def fetch_weather(self, location: MobileLocationRecord) -> WeatherSnapshot:
        """Fetch normalized weather for one location."""


@dataclass(frozen=True, slots=True)
class _CacheEntry:
    value: object
    expires_at: float


class ForgeCallsignInfoService:
    """Aggregate QRZ, Wavelog, and simple current weather for one callsign."""

    def __init__(
        self,
        qrz_lookup: QrzProfileLookup,
        wavelog: WavelogHistoryLookup,
        weather: CallsignWeatherProvider | None,
        *,
        profile_ttl_s: float = 60 * 24 * 60 * 60,
        negative_profile_ttl_s: float = 24 * 60 * 60,
        history_ttl_s: float = 60,
        station_ttl_s: float = 6 * 60 * 60,
        weather_ttl_s: float = 15 * 60,
        monotonic_clock: MonotonicClock = monotonic,
        utc_clock: UtcClock | None = None,
    ) -> None:
        for value in (
            profile_ttl_s,
            negative_profile_ttl_s,
            history_ttl_s,
            station_ttl_s,
            weather_ttl_s,
        ):
            if value <= 0:
                raise ValueError("Callsign-info cache TTLs must be positive.")
        self._qrz_lookup = qrz_lookup
        self._wavelog = wavelog
        self._weather = weather
        self._profile_ttl_s = profile_ttl_s
        self._negative_profile_ttl_s = negative_profile_ttl_s
        self._history_ttl_s = history_ttl_s
        self._station_ttl_s = station_ttl_s
        self._weather_ttl_s = weather_ttl_s
        self._monotonic = monotonic_clock
        self._utc_now = utc_clock or (lambda: datetime.now(UTC))
        self._lock = RLock()
        self._profile_cache: dict[str, _CacheEntry] = {}
        self._history_cache: dict[str, _CacheEntry] = {}
        self._weather_cache: dict[tuple[float, float], _CacheEntry] = {}
        self._station_cache: _CacheEntry | None = None

    def lookup(
        self,
        callsign: str,
        *,
        target_latitude: float | None = None,
        target_longitude: float | None = None,
        target_source: Literal["pota"] | None = None,
    ) -> CallsignInfoResponse:
        """Return one compact response; optional provider failures degrade gracefully."""
        normalized = normalize_qrz_callsign(callsign)
        if not normalized:
            raise ValueError("Callsign must not be blank.")

        profile = self._profile(normalized)
        history = self._history(normalized)
        last_qso = self._last_qso_presentation(history)
        weather = self._weather_presentation(
            profile,
            target_latitude=target_latitude,
            target_longitude=target_longitude,
            target_source=target_source,
        )
        return CallsignInfoResponse(
            callsign=normalized,
            profile=self._profile_presentation(profile),
            last_qso=last_qso,
            weather=weather,
        )

    def invalidate_history(self, callsign: str) -> None:
        """Allow contact-sync success to invalidate one mutable last-QSO cache entry."""
        normalized = normalize_qrz_callsign(callsign)
        with self._lock:
            self._history_cache.pop(normalized, None)

    def _profile(self, callsign: str) -> QrzCallsignProfile | None:
        now = self._monotonic()
        with self._lock:
            entry = self._profile_cache.get(callsign)
            if entry is not None and entry.expires_at > now:
                return entry.value if isinstance(entry.value, QrzCallsignProfile) else None

        profile = self._qrz_lookup.lookup_profile(callsign)

        ttl = self._profile_ttl_s if profile is not None else self._negative_profile_ttl_s
        with self._lock:
            self._profile_cache[callsign] = _CacheEntry(profile, now + ttl)
        return profile

    def _history(self, callsign: str) -> WavelogQsoSummary | None:
        now = self._monotonic()
        with self._lock:
            entry = self._history_cache.get(callsign)
            if entry is not None and entry.expires_at > now:
                return entry.value if isinstance(entry.value, WavelogQsoSummary) else None

        qso = self._wavelog.latest_qso(callsign)

        with self._lock:
            self._history_cache[callsign] = _CacheEntry(qso, now + self._history_ttl_s)
        return qso

    def _station_names(self) -> dict[int, str]:
        now = self._monotonic()
        with self._lock:
            entry = self._station_cache
            if entry is not None and entry.expires_at > now and isinstance(entry.value, dict):
                return dict(entry.value)

        locations = self._wavelog.list_station_locations()
        names = {item.station_id: item.name for item in locations}
        with self._lock:
            self._station_cache = _CacheEntry(names, now + self._station_ttl_s)
        return names

    def _last_qso_presentation(self, qso: WavelogQsoSummary | None) -> CallsignInfoLastQso:
        if qso is None:
            return CallsignInfoLastQso(exists=False)

        station_location = None
        if qso.station_id is not None:
            station_location = self._station_names().get(qso.station_id)
        mobile = None
        if station_location is not None:
            mobile = "mobile" in station_location.casefold()

        return CallsignInfoLastQso(
            exists=True,
            worked_count=qso.worked_count,
            band=qso.band,
            occurred_at=qso.occurred_at,
            station_location=station_location,
            comments=qso.comments,
            notes=qso.notes,
            qth=qso.qth,
            grid=qso.grid,
            pota_reference=qso.pota_reference,
            my_pota_reference=qso.my_pota_reference,
            mobile=mobile,
        )

    def _weather_presentation(
        self,
        profile: QrzCallsignProfile | None,
        *,
        target_latitude: float | None,
        target_longitude: float | None,
        target_source: Literal["pota"] | None,
    ) -> CallsignInfoWeather | None:
        provider = self._weather
        if provider is None:
            return None

        source: Literal["pota", "qrz"]
        if (
            target_source == "pota"
            and target_latitude is not None
            and target_longitude is not None
        ):
            latitude = target_latitude
            longitude = target_longitude
            source = "pota"
        elif (
            profile is not None
            and profile.latitude is not None
            and profile.longitude is not None
            and (profile.geoloc or "").casefold() not in {"state", "dxcc"}
        ):
            latitude = profile.latitude
            longitude = profile.longitude
            source = "qrz"
        elif (
            profile is not None
            and profile.grid is not None
            and (profile.geoloc or "").casefold() not in {"state", "dxcc"}
        ):
            try:
                latitude, longitude = maidenhead_grid_center(profile.grid)
            except ValueError:
                return None
            source = "qrz"
        else:
            return None

        key = (round(latitude, 4), round(longitude, 4))
        now = self._monotonic()
        with self._lock:
            entry = self._weather_cache.get(key)
            if entry is not None and entry.expires_at > now:
                snapshot = entry.value if isinstance(entry.value, WeatherSnapshot) else None
            else:
                snapshot = None

        if snapshot is None:
            stamp = self._utc_now().astimezone(UTC)
            try:
                snapshot = provider.fetch_weather(
                    MobileLocationRecord(
                        latitude=latitude,
                        longitude=longitude,
                        fix_at=stamp,
                        received_at=stamp,
                    )
                )
            except (ForgeWeatherProviderError, OSError, ValueError):
                return None
            with self._lock:
                self._weather_cache[key] = _CacheEntry(
                    snapshot,
                    now + self._weather_ttl_s,
                )

        return CallsignInfoWeather(
            temperature_f=round(snapshot.current.temperature_c * 9 / 5 + 32),
            condition=_condition_text(
                snapshot.current.condition,
                is_day=snapshot.current.is_day,
            ),
            location_source=source,
            attribution=snapshot.source.attribution_text,
            timezone=snapshot.timezone,
            observation=weather_observation_from_snapshot(snapshot),
        )

    @staticmethod
    def _profile_presentation(
        profile: QrzCallsignProfile | None,
    ) -> CallsignInfoProfile | None:
        if profile is None:
            return None
        return CallsignInfoProfile(
            callsign=profile.callsign,
            name=profile.name,
            address1=profile.address1,
            address2=profile.address2,
            state=profile.state,
            country=profile.country,
            grid=str(profile.grid) if profile.grid is not None else None,
            latitude=profile.latitude,
            longitude=profile.longitude,
            coordinate_source=profile.geoloc,
            license_class=profile.license_class,
            license_effective_date=profile.license_effective_date,
            license_expiration_date=profile.license_expiration_date,
            birth_year=profile.birth_year,
        )


def _condition_text(
    condition: WeatherConditionToken,
    *,
    is_day: bool,
) -> str:
    mapping = {
        WeatherConditionToken.CLEAR: "SUNNY" if is_day else "CLEAR",
        WeatherConditionToken.PARTLY_CLOUDY: "PARTLY CLOUDY",
        WeatherConditionToken.CLOUDY: "CLOUDY",
        WeatherConditionToken.FOG: "FOG",
        WeatherConditionToken.DRIZZLE: "DRIZZLE",
        WeatherConditionToken.RAIN: "RAIN",
        WeatherConditionToken.FREEZING_RAIN: "ICE / FREEZING RAIN",
        WeatherConditionToken.SNOW: "SNOW",
        WeatherConditionToken.SHOWERS: "SHOWERS",
        WeatherConditionToken.THUNDERSTORM: "THUNDERSTORMS",
        WeatherConditionToken.UNKNOWN: "UNKNOWN",
    }
    return mapping[condition]
