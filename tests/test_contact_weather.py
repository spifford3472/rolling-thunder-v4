"""Forge-side best-effort weather enrichment for immutable contacts."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from rolling_thunder.contact_weather import ForgeContactWeatherEnricher
from rolling_thunder.domain import Contact
from rolling_thunder.forge_contact_sync import (
    ForgeContactSyncRepository,
    ForgeContactSyncService,
)
from rolling_thunder.forge_mobile_location import MobileLocationRecord
from rolling_thunder.forge_weather import (
    ForgeWeatherProviderError,
    WeatherConditionToken,
    WeatherCurrent,
    WeatherHourlyPoint,
    WeatherIconToken,
    WeatherSnapshot,
    WeatherSolar,
    WeatherSourceMetadata,
)
from rolling_thunder.wavelog import (
    WavelogStationLocation,
    WavelogStationTarget,
    WavelogUploadDisposition,
    contact_to_adif,
)

NOW = datetime(2026, 10, 7, 3, 0, tzinfo=UTC)


class RecordingProvider:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.locations: list[MobileLocationRecord] = []

    def fetch_weather(self, location: MobileLocationRecord) -> WeatherSnapshot:
        self.locations.append(location)
        if self.fail:
            raise ForgeWeatherProviderError("offline")
        return WeatherSnapshot(
            latitude=location.latitude,
            longitude=location.longitude,
            source_at=NOW,
            fetched_at=NOW + timedelta(seconds=2),
            current=WeatherCurrent(
                temperature_c=21.5,
                relative_humidity_percent=57,
                condition=WeatherConditionToken.PARTLY_CLOUDY,
                icon=WeatherIconToken.PARTLY_CLOUDY_NIGHT,
                is_day=False,
            ),
            hourly=tuple(
                WeatherHourlyPoint(
                    forecast_at=NOW + timedelta(hours=hour),
                    temperature_c=21.5,
                    precipitation_probability_percent=10,
                )
                for hour in (1, 2, 3)
            ),
            solar=WeatherSolar(
                sunrise_at=NOW + timedelta(hours=3),
                sunset_at=NOW + timedelta(hours=15),
            ),
            source=WeatherSourceMetadata(
                provider_id="open_meteo",
                provider_name="Open-Meteo",
                attribution_text="Weather data by Open-Meteo.com",
                attribution_url="https://open-meteo.com/",
                license_name="CC BY 4.0",
                license_url="https://creativecommons.org/licenses/by/4.0/",
            ),
        )


class RecordingWavelog:
    def __init__(self) -> None:
        self.uploaded: list[Contact] = []

    def verify_health_target(self) -> None:
        return None

    def resolve_station_target(self, contact: Contact) -> WavelogStationTarget:
        del contact
        return WavelogStationTarget(
            WavelogStationLocation(42, "Mobile", "mobile-uuid"),
            dynamic=False,
        )

    def upload_contact(
        self, contact: Contact, *, target: WavelogStationTarget
    ) -> WavelogUploadDisposition:
        del target
        self.uploaded.append(contact)
        return WavelogUploadDisposition.IMPORTED


def contact(**updates: object) -> Contact:
    return Contact.model_validate(
        {
            "contact_id": "11111111-2222-3333-4444-555555555555",
            "callsign": "W1AW",
            "frequency_hz": 14_250_000,
            "mode": "USB",
            "started_at": NOW,
            "rst_sent": "59",
            "rst_received": "59",
            "grid": "FN31pr",
            "contact_latitude": 41.25,
            "contact_longitude": -72.75,
            "my_grid": "EM79xm",
            "my_latitude": 39.53,
            "my_longitude": -84.09,
            "weather_notes_enabled": True,
            **updates,
        }
    )


def test_enrichment_prefers_frozen_park_coordinates_and_captures_provenance() -> None:
    provider = RecordingProvider()

    enriched = ForgeContactWeatherEnricher(provider).enrich(contact())

    assert [(item.latitude, item.longitude) for item in provider.locations] == [
        (41.25, -72.75),
        (39.53, -84.09),
    ]
    observation = enriched.contact_weather
    assert observation is not None
    assert observation.provider_id == "open_meteo"
    assert observation.provider_name == "Open-Meteo"
    assert observation.observed_at == NOW
    assert observation.latitude == 41.25
    assert observation.condition == "partly_cloudy"
    assert observation.temperature_c == 21.5
    assert observation.relative_humidity_percent == 57


def test_enrichment_uses_remote_grid_center_only_when_coordinates_are_absent() -> None:
    provider = RecordingProvider()

    ForgeContactWeatherEnricher(provider).enrich(
        contact(contact_latitude=None, contact_longitude=None)
    )

    assert (provider.locations[0].latitude, provider.locations[0].longitude) != (
        41.25,
        -72.75,
    )
    assert len(provider.locations) == 2


def test_weather_failure_never_prevents_wavelog_sync_and_emits_na(tmp_path: Path) -> None:
    provider = RecordingProvider(fail=True)
    wavelog = RecordingWavelog()
    service = ForgeContactSyncService(
        ForgeContactSyncRepository(tmp_path / "forge.db"),
        wavelog,
        weather_enricher=ForgeContactWeatherEnricher(provider),
    )

    service.synchronize(contact())

    assert len(wavelog.uploaded) == 1
    adif = contact_to_adif(wavelog.uploaded[0])
    assert "Contact Wx: N/A\nLocal Wx: N/A" in adif


def test_weather_result_is_frozen_for_retry_idempotency(tmp_path: Path) -> None:
    provider = RecordingProvider()
    repository = ForgeContactSyncRepository(tmp_path / "forge.db")
    source = contact()
    first = ForgeContactWeatherEnricher(provider).enrich(source)
    frozen = repository.resolve_weather_snapshot(source, first)
    provider.fail = True
    failed_candidate = ForgeContactWeatherEnricher(provider).enrich(source)

    replay = repository.resolve_weather_snapshot(source, failed_candidate)

    assert replay == frozen
    assert replay.contact_weather is not None
