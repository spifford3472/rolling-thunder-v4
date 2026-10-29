"""Forge-side best-effort weather enrichment for immutable contacts."""

from datetime import UTC, datetime, timedelta
from inspect import signature
from pathlib import Path

from rolling_thunder.callsign_info import (
    CallsignInfoLastQso,
    CallsignInfoResponse,
    CallsignInfoWeather,
)
from rolling_thunder.callsign_info_service import CallsignInfoState
from rolling_thunder.contact_weather import (
    ForgeContactWeatherEnricher,
    PublishedContactWeatherSnapshotProvider,
    weather_observation_from_snapshot,
)
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
from rolling_thunder.pi_forge_weather_service import (
    PiForgeWeatherState,
    PiForgeWeatherStateKind,
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


def published_weather_provider(
    *,
    remote_callsign: str = "W1AW",
    remote_age: timedelta = timedelta(0),
    remote_grid: str = "FN31pr",
    include_remote: bool = True,
    local_stale: bool = False,
    local_latitude: float = 39.53,
    local_longitude: float = -84.09,
) -> PublishedContactWeatherSnapshotProvider:
    local_snapshot = RecordingProvider().fetch_weather(
        MobileLocationRecord(
            latitude=local_latitude,
            longitude=local_longitude,
            fix_at=NOW,
            received_at=NOW,
        )
    )
    remote_snapshot = RecordingProvider().fetch_weather(
        MobileLocationRecord(
            latitude=41.25 if remote_grid == "FN31pr" else 39.53,
            longitude=-72.75 if remote_grid == "FN31pr" else -84.09,
            fix_at=NOW,
            received_at=NOW,
        )
    )
    remote_observation = weather_observation_from_snapshot(remote_snapshot).model_copy(
        update={
            "observed_at": NOW - remote_age,
            "fetched_at": NOW - remote_age,
        }
    )
    response = CallsignInfoResponse(
        callsign=remote_callsign,
        last_qso=CallsignInfoLastQso(exists=False),
        weather=(
            CallsignInfoWeather(
                temperature_f=71,
                condition="PARTLY CLOUDY",
                location_source="qrz",
                timezone="America/New_York",
                observation=remote_observation,
            )
            if include_remote
            else None
        ),
    )
    callsign_state = CallsignInfoState(
        generation=1,
        enabled=True,
        callsign=remote_callsign,
        loading=False,
        response=response,
        shown_at_monotonic=100.0,
        target_latitude=remote_snapshot.latitude,
        target_longitude=remote_snapshot.longitude,
    )
    local_state = PiForgeWeatherState(
        kind=PiForgeWeatherStateKind.RETAINED,
        snapshot_revision=1,
        snapshot=local_snapshot,
        stale=local_stale,
        last_success_at=NOW,
    )
    return PublishedContactWeatherSnapshotProvider(
        lambda: local_state,
        lambda: callsign_state,
    )


def test_published_snapshot_captures_fresh_matching_endpoint_weather() -> None:
    snapshot = published_weather_provider().capture(contact())

    assert snapshot.contact is not None
    assert snapshot.contact.latitude == 41.25
    assert snapshot.local is not None
    assert snapshot.local.latitude == 39.53


def test_published_snapshot_matches_local_weather_by_frozen_grid_without_coordinates() -> None:
    snapshot = published_weather_provider().capture(
        contact(my_grid="EM79wm", my_latitude=None, my_longitude=None)
    )

    assert snapshot.local is not None
    assert snapshot.local.latitude == 39.53


def test_published_snapshot_rejects_retained_local_weather_for_another_location() -> None:
    mismatched_coordinates = published_weather_provider(
        local_latitude=39.70,
    ).capture(contact())
    mismatched_grid = published_weather_provider(
        local_latitude=40.0,
        local_longitude=-83.0,
    ).capture(contact(my_latitude=None, my_longitude=None))

    assert mismatched_coordinates.local is None
    assert mismatched_grid.local is None


def test_published_snapshot_rejects_stale_or_mismatched_remote_weather() -> None:
    stale = published_weather_provider(remote_age=timedelta(minutes=31)).capture(contact())
    mismatched_call = published_weather_provider(remote_callsign="K1ABC").capture(contact())
    mismatched_grid = published_weather_provider(remote_grid="EM79xm").capture(contact())

    assert stale.contact is None
    assert mismatched_call.contact is None
    assert mismatched_grid.contact is None
    assert stale.local is not None


def test_published_snapshot_keeps_missing_and_stale_weather_absent() -> None:
    snapshot = published_weather_provider(
        include_remote=False,
        local_stale=True,
    ).capture(contact())

    assert snapshot.contact is None
    assert snapshot.local is None


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


def test_contact_sync_never_invokes_weather_enrichment(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def fail_if_invoked(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("contact synchronization must not invoke a weather provider")

    monkeypatch.setattr(ForgeContactWeatherEnricher, "enrich", fail_if_invoked)
    wavelog = RecordingWavelog()
    service = ForgeContactSyncService(
        ForgeContactSyncRepository(tmp_path / "forge.db"),
        wavelog,
    )
    source = contact()

    service.synchronize(source)

    assert "weather_enricher" not in signature(ForgeContactSyncService).parameters
    assert len(wavelog.uploaded) == 1
    assert wavelog.uploaded[0] is source
    adif = contact_to_adif(wavelog.uploaded[0])
    assert "Contact Wx:" not in adif
    assert "Local Wx:" not in adif


def test_contact_sync_preserves_weather_already_present_on_immutable_payload(
    tmp_path: Path,
) -> None:
    provider = RecordingProvider()
    source = ForgeContactWeatherEnricher(provider).enrich(contact())
    wavelog = RecordingWavelog()
    service = ForgeContactSyncService(
        ForgeContactSyncRepository(tmp_path / "forge.db"),
        wavelog,
    )

    service.synchronize(source)

    assert wavelog.uploaded == [source]
    assert "Contact Wx:" not in contact_to_adif(source)
