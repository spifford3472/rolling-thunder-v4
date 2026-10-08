"""Best-effort Forge weather enrichment for immutable QSO snapshots."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import asin, cos, radians, sin, sqrt
from typing import Protocol

from rolling_thunder.callsign_info_service import CallsignInfoState
from rolling_thunder.domain import Contact, ContactWeatherObservation
from rolling_thunder.forge_mobile_location import MobileLocationRecord
from rolling_thunder.forge_weather import (
    ForgeWeatherProviderError,
    WeatherProvider,
    WeatherSnapshot,
)
from rolling_thunder.maidenhead import maidenhead_grid, maidenhead_grid_center
from rolling_thunder.pi_forge_weather_service import PiForgeWeatherState

_MAX_OBSERVATION_AGE = timedelta(minutes=30)
_MAX_FUTURE_SKEW = timedelta(minutes=5)
_LOCAL_WEATHER_LOCATION_TOLERANCE_KM = 10.0


@dataclass(frozen=True, slots=True)
class ContactWeatherSnapshot:
    """Already-published endpoint weather frozen for one contact."""

    contact: ContactWeatherObservation | None = None
    local: ContactWeatherObservation | None = None


class ContactWeatherSnapshotProvider(Protocol):
    """Read already-published weather without provider or storage I/O."""

    def capture(self, contact: Contact) -> ContactWeatherSnapshot: ...


class PublishedContactWeatherSnapshotProvider:
    """Project retained Pi and callsign-info weather into an immutable QSO."""

    def __init__(
        self,
        local_state: Callable[[], PiForgeWeatherState],
        callsign_state: Callable[[], CallsignInfoState | None],
    ) -> None:
        self._local_state = local_state
        self._callsign_state = callsign_state

    def capture(self, contact: Contact) -> ContactWeatherSnapshot:
        """Return only fresh weather proven to belong to the QSO endpoints."""
        return ContactWeatherSnapshot(
            contact=self._contact_observation(contact),
            local=self._local_observation(contact),
        )

    def _local_observation(self, contact: Contact) -> ContactWeatherObservation | None:
        state = self._local_state()
        snapshot = state.snapshot
        if state.stale or snapshot is None:
            return None
        observation = weather_observation_from_snapshot(snapshot)
        if not self._is_fresh(observation, contact.started_at):
            return None
        if not self._matches_local_location(contact, observation):
            return None
        return observation

    def _contact_observation(self, contact: Contact) -> ContactWeatherObservation | None:
        state = self._callsign_state()
        if state is None or state.response is None:
            return None
        response = state.response
        callsign = str(contact.callsign).upper()
        if state.callsign != callsign or response.callsign.upper() != callsign:
            return None
        weather = response.weather
        if weather is None or weather.observation is None:
            return None
        observation = weather.observation
        if not self._is_fresh(observation, contact.started_at):
            return None
        if not self._matches_remote_target(contact, state, observation):
            return None
        return observation

    @staticmethod
    def _is_fresh(
        observation: ContactWeatherObservation,
        reference: datetime,
    ) -> bool:
        observed_at = observation.observed_at
        fetched_at = observation.fetched_at
        if observed_at is None or fetched_at is None:
            return False
        reference_utc = reference.astimezone(UTC)
        return (
            reference_utc - observed_at <= _MAX_OBSERVATION_AGE
            and reference_utc - fetched_at <= _MAX_OBSERVATION_AGE
            and observed_at - reference_utc <= _MAX_FUTURE_SKEW
            and fetched_at - reference_utc <= _MAX_FUTURE_SKEW
        )

    @staticmethod
    def _matches_remote_target(
        contact: Contact,
        state: CallsignInfoState,
        observation: ContactWeatherObservation,
    ) -> bool:
        latitude = observation.latitude
        longitude = observation.longitude
        if latitude is None or longitude is None:
            return False
        if contact.contact_latitude is not None and contact.contact_longitude is not None:
            return (
                state.target_latitude is not None
                and state.target_longitude is not None
                and abs(state.target_latitude - contact.contact_latitude) < 0.0001
                and abs(state.target_longitude - contact.contact_longitude) < 0.0001
                and abs(latitude - contact.contact_latitude) < 0.0001
                and abs(longitude - contact.contact_longitude) < 0.0001
            )
        if contact.grid is None:
            return True
        try:
            weather_grid = maidenhead_grid(latitude, longitude)
        except ValueError:
            return False
        expected = str(contact.grid).upper()
        return weather_grid.upper()[: len(expected)] == expected

    @staticmethod
    def _matches_local_location(
        contact: Contact,
        observation: ContactWeatherObservation,
    ) -> bool:
        latitude = observation.latitude
        longitude = observation.longitude
        if latitude is None or longitude is None:
            return False
        if contact.my_latitude is not None and contact.my_longitude is not None:
            return (
                _distance_km(
                    contact.my_latitude,
                    contact.my_longitude,
                    latitude,
                    longitude,
                )
                < _LOCAL_WEATHER_LOCATION_TOLERANCE_KM
            )
        if contact.my_grid is None:
            return False
        try:
            weather_grid = maidenhead_grid(latitude, longitude)
        except ValueError:
            return False
        expected = str(contact.my_grid).upper()
        return weather_grid.upper()[: len(expected)] == expected


class ContactWeatherEnricher(Protocol):
    """Enrich one immutable contact without changing its durable identity."""

    def enrich(self, contact: Contact) -> Contact: ...


class ForgeContactWeatherEnricher:
    """Resolve both QSO endpoints through the shared Forge weather provider."""

    def __init__(self, provider: WeatherProvider) -> None:
        self._provider = provider

    def enrich(self, contact: Contact) -> Contact:
        """Return a copy with independently best-effort endpoint observations."""
        if not contact.weather_notes_enabled:
            return contact
        contact_weather = contact.contact_weather
        local_weather = contact.local_weather
        if contact_weather is None:
            contact_weather = self._fetch(self._contact_coordinates(contact))
        if local_weather is None:
            local_weather = self._fetch(self._local_coordinates(contact))
        return contact.model_copy(
            update={
                "contact_weather": contact_weather,
                "local_weather": local_weather,
            }
        )

    def _fetch(
        self, coordinates: tuple[float, float] | None
    ) -> ContactWeatherObservation | None:
        if coordinates is None:
            return None
        now = datetime.now(UTC)
        location = MobileLocationRecord(
            latitude=coordinates[0],
            longitude=coordinates[1],
            fix_at=now,
            received_at=now,
        )
        try:
            snapshot = self._provider.fetch_weather(location)
        except (ForgeWeatherProviderError, OSError, RuntimeError, ValueError):
            return None
        return weather_observation_from_snapshot(snapshot)

    @staticmethod
    def _contact_coordinates(contact: Contact) -> tuple[float, float] | None:
        if contact.contact_latitude is not None and contact.contact_longitude is not None:
            return contact.contact_latitude, contact.contact_longitude
        if contact.grid is None:
            return None
        try:
            return maidenhead_grid_center(contact.grid)
        except ValueError:
            return None

    @staticmethod
    def _local_coordinates(contact: Contact) -> tuple[float, float] | None:
        if contact.my_latitude is None or contact.my_longitude is None:
            return None
        return contact.my_latitude, contact.my_longitude


def weather_observation_from_snapshot(
    snapshot: WeatherSnapshot,
) -> ContactWeatherObservation:
    """Project the shared normalized weather snapshot into the QSO contract."""
    current = snapshot.current
    condition = current.condition.value
    summary = (
        f"{condition.replace('_', ' ').title()}; "
        f"{current.temperature_c:.1f} C; "
        f"humidity {current.relative_humidity_percent:.0f}%"
    )
    return ContactWeatherObservation(
        summary=summary,
        provider_id=snapshot.source.provider_id,
        provider_name=snapshot.source.provider_name,
        observed_at=snapshot.source_at,
        fetched_at=snapshot.fetched_at,
        latitude=snapshot.latitude,
        longitude=snapshot.longitude,
        condition=condition,
        temperature_c=current.temperature_c,
        relative_humidity_percent=current.relative_humidity_percent,
    )


def _distance_km(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    """Return deterministic great-circle distance between WGS84 coordinates."""
    earth_radius_km = 6_371.0088
    latitude_a_radians = radians(latitude_a)
    latitude_b_radians = radians(latitude_b)
    delta_latitude = radians(latitude_b - latitude_a)
    delta_longitude = radians(longitude_b - longitude_a)
    haversine = (
        sin(delta_latitude / 2.0) ** 2
        + cos(latitude_a_radians)
        * cos(latitude_b_radians)
        * sin(delta_longitude / 2.0) ** 2
    )
    return 2.0 * earth_radius_km * asin(min(1.0, sqrt(haversine)))
