"""Best-effort Forge weather enrichment for immutable QSO snapshots."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from rolling_thunder.domain import Contact, ContactWeatherObservation
from rolling_thunder.forge_mobile_location import MobileLocationRecord
from rolling_thunder.forge_weather import (
    ForgeWeatherProviderError,
    WeatherProvider,
    WeatherSnapshot,
)
from rolling_thunder.maidenhead import maidenhead_grid_center


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
