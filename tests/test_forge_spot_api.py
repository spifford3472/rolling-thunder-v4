"""Tests for the versioned read-only Forge spot API."""

from datetime import UTC, datetime
from json import loads

from rolling_thunder.domain import Frequency, RadioMode
from rolling_thunder.forge_spot_aggregation import (
    ForgeAggregationState,
    ForgeProviderHealth,
    ForgeProviderHealthStatus,
)
from rolling_thunder.forge_spot_api import (
    ForgeServiceStatus,
    ForgeSpotApiApplication,
    derive_service_status,
)
from rolling_thunder.spot_domain import (
    PotaSpotIdentity,
    PotaSpotMetadata,
    SpotProvider,
    SpotRecord,
    SpotSnapshot,
)

BASE_TIME = datetime(2026, 8, 5, 20, 0, tzinfo=UTC)


class RecordingStateSource:
    def __init__(self, state: ForgeAggregationState) -> None:
        self.state = state
        self.get_count = 0

    def get_state(self) -> ForgeAggregationState:
        self.get_count += 1
        return self.state


def provider_health(
    status: ForgeProviderHealthStatus,
    *,
    count: int = 0,
    error: str | None = None,
) -> ForgeProviderHealth:
    attempted = None if status is ForgeProviderHealthStatus.STARTING else BASE_TIME
    succeeded = (
        BASE_TIME
        if status in {
            ForgeProviderHealthStatus.HEALTHY,
            ForgeProviderHealthStatus.DEGRADED,
        }
        else None
    )
    return ForgeProviderHealth(
        provider=SpotProvider.POTA,
        status=status,
        active_spot_count=count,
        last_attempt_at=attempted,
        last_success_at=succeeded,
        last_error=error,
    )


def state_with(
    status: ForgeProviderHealthStatus,
    *,
    revision: int = 0,
    spots: tuple[SpotRecord, ...] = (),
    startup_storage_error: str | None = None,
    persistence_error: str | None = None,
) -> ForgeAggregationState:
    return ForgeAggregationState(
        revision=revision,
        snapshot=SpotSnapshot(
            generated_at=BASE_TIME,
            spots=spots,
        ),
        providers=(
            provider_health(
                status,
                count=len(spots),
                error=(
                    "provider failed"
                    if status in {
                        ForgeProviderHealthStatus.DEGRADED,
                        ForgeProviderHealthStatus.UNAVAILABLE,
                    }
                    else None
                ),
            ),
        ),
        startup_storage_error=startup_storage_error,
        persistence_error=persistence_error,
    )


def pota_spot() -> SpotRecord:
    frequency = Frequency(hz=14_250_000)
    return SpotRecord(
        identity=PotaSpotIdentity(
            park_reference="US-1234",
            frequency=frequency,
        ),
        callsign="KI5VNB",
        frequency=frequency,
        mode=RadioMode.USB,
        display_mode="SSB",
        spotted_at=BASE_TIME,
        pota=PotaSpotMetadata(
            park_reference="US-1234",
            park_name="Test Park",
            location_code="US-OH",
        ),
    )


def header_value(response_headers: tuple[tuple[str, str], ...], name: str) -> str:
    return dict(response_headers)[name]


def test_health_endpoint_returns_starting_state_and_explicit_json_headers() -> None:
    source = RecordingStateSource(state_with(ForgeProviderHealthStatus.STARTING))
    response = ForgeSpotApiApplication(source).handle("GET", "/api/v1/health")
    payload = loads(response.body)

    assert response.status_code == 200
    assert header_value(response.headers, "Content-Type") == "application/json; charset=utf-8"
    assert header_value(response.headers, "Content-Length") == str(len(response.body))
    assert header_value(response.headers, "Cache-Control") == "no-store"
    assert payload["api_schema_version"] == "1"
    assert payload["service_status"] == "starting"
    assert payload["snapshot_revision"] == 0
    assert payload["active_spot_count"] == 0
    assert payload["providers"][0]["provider"] == "pota"
    assert source.get_count == 1


def test_successful_empty_snapshot_is_healthy() -> None:
    state = state_with(
        ForgeProviderHealthStatus.HEALTHY,
        revision=1,
    )

    assert derive_service_status(state) is ForgeServiceStatus.HEALTHY


def test_unavailable_without_durable_snapshot_is_unavailable() -> None:
    state = state_with(ForgeProviderHealthStatus.UNAVAILABLE)

    assert derive_service_status(state) is ForgeServiceStatus.UNAVAILABLE


def test_retained_or_storage_error_state_is_degraded() -> None:
    retained = state_with(
        ForgeProviderHealthStatus.DEGRADED,
        revision=2,
        spots=(pota_spot(),),
    )
    storage_error = state_with(
        ForgeProviderHealthStatus.HEALTHY,
        revision=2,
        persistence_error="disk full",
    )

    assert derive_service_status(retained) is ForgeServiceStatus.DEGRADED
    assert derive_service_status(storage_error) is ForgeServiceStatus.DEGRADED


def test_spots_endpoint_serializes_complete_canonical_snapshot_and_provider_age() -> None:
    spot = pota_spot()
    source = RecordingStateSource(
        state_with(
            ForgeProviderHealthStatus.HEALTHY,
            revision=7,
            spots=(spot,),
        )
    )

    response = ForgeSpotApiApplication(source).handle(
        "GET",
        "/api/v1/spots?ignored=true",
    )
    payload = loads(response.body)

    assert response.status_code == 200
    assert payload["api_schema_version"] == "1"
    assert payload["snapshot_revision"] == 7
    assert payload["generated_at"] == "2026-08-05T20:00:00Z"
    assert payload["spots"][0]["callsign"] == "KI5VNB"
    assert payload["spots"][0]["frequency"] == {"hz": 14_250_000}
    assert payload["spots"][0]["identity"]["provider"] == "pota"
    assert payload["spots"][0]["pota"]["park_reference"] == "US-1234"
    assert payload["providers"][0]["last_success_at"] == "2026-08-05T20:00:00Z"
    assert source.get_count == 1


def test_unknown_path_returns_404_without_reading_state() -> None:
    source = RecordingStateSource(state_with(ForgeProviderHealthStatus.STARTING))

    response = ForgeSpotApiApplication(source).handle("GET", "/api/v1/missing")
    payload = loads(response.body)

    assert response.status_code == 404
    assert payload["error"] == "not_found"
    assert source.get_count == 0


def test_unsupported_method_returns_405_without_reading_state() -> None:
    source = RecordingStateSource(state_with(ForgeProviderHealthStatus.STARTING))

    response = ForgeSpotApiApplication(source).handle("POST", "/api/v1/spots")
    payload = loads(response.body)

    assert response.status_code == 405
    assert header_value(response.headers, "Allow") == "GET"
    assert payload["error"] == "method_not_allowed"
    assert source.get_count == 0


def test_repeated_response_is_byte_for_byte_deterministic() -> None:
    source = RecordingStateSource(
        state_with(
            ForgeProviderHealthStatus.HEALTHY,
            revision=1,
            spots=(pota_spot(),),
        )
    )
    application = ForgeSpotApiApplication(source)

    first = application.handle("GET", "/api/v1/spots")
    second = application.handle("GET", "/api/v1/spots")

    assert first == second
    assert source.get_count == 2
