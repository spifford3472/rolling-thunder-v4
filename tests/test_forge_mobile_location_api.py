"""Tests for the bounded versioned Forge mobile-location write endpoint."""

from datetime import UTC, datetime, timedelta
from json import dumps, loads

from rolling_thunder.forge_mobile_location import (
    ForgeMobileLocationService,
    ForgeMobileLocationStorageError,
    MobileLocationRecord,
    MobileLocationState,
    StaleMobileLocationError,
)
from rolling_thunder.forge_spot_aggregation import (
    ForgeAggregationState,
    ForgeProviderHealth,
    ForgeProviderHealthStatus,
)
from rolling_thunder.forge_spot_api import (
    MAX_MOBILE_LOCATION_PAYLOAD_BYTES,
    ForgeSpotApiApplication,
)
from rolling_thunder.spot_domain import SpotProvider, SpotSnapshot

BASE_TIME = datetime(2026, 8, 8, 23, 30, tzinfo=UTC)


class StaticSpotStateSource:
    def __init__(self) -> None:
        self.reads = 0
        self.state = ForgeAggregationState(
            revision=0,
            snapshot=SpotSnapshot.empty(generated_at=BASE_TIME),
            providers=(
                ForgeProviderHealth(
                    provider=SpotProvider.POTA,
                    status=ForgeProviderHealthStatus.STARTING,
                    active_spot_count=0,
                ),
            ),
        )

    def get_state(self) -> ForgeAggregationState:
        self.reads += 1
        return self.state


class RecordingRepository:
    def __init__(self) -> None:
        self.state: MobileLocationState | None = None
        self.error: Exception | None = None

    def load(self) -> MobileLocationState | None:
        return self.state

    def replace(self, location: MobileLocationRecord) -> MobileLocationState:
        if self.error is not None:
            raise self.error
        revision = 1 if self.state is None else self.state.revision + 1
        self.state = MobileLocationState(revision=revision, location=location)
        return self.state


def application(
    repository: RecordingRepository | None = None,
) -> tuple[ForgeSpotApiApplication, StaticSpotStateSource, RecordingRepository]:
    source = StaticSpotStateSource()
    repo = repository or RecordingRepository()
    service = ForgeMobileLocationService(
        repo,
        now=lambda: BASE_TIME + timedelta(seconds=5),
    )
    return (
        ForgeSpotApiApplication(source, mobile_location=service),
        source,
        repo,
    )


def request_body(**location_updates: object) -> bytes:
    location: dict[str, object] = {
        "latitude": 39.529,
        "longitude": -84.064,
        "fix_at": "2026-08-08T23:30:00Z",
        "received_at": "2026-08-08T23:30:01Z",
        "speed_m_s": 18.5,
        "heading_degrees": 90.0,
    }
    location.update(location_updates)
    return dumps(
        {
            "api_schema_version": "1",
            "location": location,
        }
    ).encode("utf-8")


def put(
    app: ForgeSpotApiApplication,
    body: bytes,
    *,
    content_type: str = "application/json",
):
    return app.handle(
        "PUT",
        "/api/v1/mobile-location",
        headers={"Content-Type": content_type},
        body=body,
    )


def test_put_accepts_valid_location_without_reading_spot_state() -> None:
    app, source, repository = application()

    response = put(app, request_body())
    payload = loads(response.body)

    assert response.status_code == 200
    assert payload["api_schema_version"] == "1"
    assert payload["revision"] == 1
    assert payload["location"]["latitude"] == 39.529
    assert payload["location"]["fix_at"] == "2026-08-08T23:30:00Z"
    assert source.reads == 0
    assert repository.state is not None


def test_endpoint_is_put_only_and_existing_spots_method_contract_is_unchanged() -> None:
    app, _, _ = application()

    mobile_get = app.handle("GET", "/api/v1/mobile-location")
    spots_put = app.handle("PUT", "/api/v1/spots")

    assert mobile_get.status_code == 405
    assert dict(mobile_get.headers)["Allow"] == "PUT"
    assert spots_put.status_code == 405
    assert dict(spots_put.headers)["Allow"] == "GET"


def test_endpoint_requires_json_and_supported_schema_version() -> None:
    app, _, _ = application()

    wrong_type = put(app, request_body(), content_type="text/plain")
    wrong_version = put(
        app,
        dumps(
            {
                "api_schema_version": "2",
                "location": {},
            }
        ).encode(),
    )

    assert wrong_type.status_code == 415
    assert loads(wrong_type.body)["error"] == "unsupported_media_type"
    assert wrong_version.status_code == 400
    assert loads(wrong_version.body)["error"] == "unsupported_schema_version"


def test_malformed_invalid_and_oversized_payloads_do_not_publish() -> None:
    app, _, repository = application()

    malformed = put(app, b"{not-json")
    invalid = put(app, request_body(latitude=91.0))
    oversized = put(app, b"{" + b"x" * MAX_MOBILE_LOCATION_PAYLOAD_BYTES + b"}")

    assert malformed.status_code == 400
    assert invalid.status_code == 422
    assert loads(invalid.body)["error"] == "invalid_location"
    assert oversized.status_code == 413
    assert repository.state is None


def test_stale_rejection_preserves_previous_accepted_location() -> None:
    repository = RecordingRepository()
    app, _, _ = application(repository)
    accepted = put(app, request_body())
    prior = repository.state
    repository.error = StaleMobileLocationError("location is stale")

    rejected = put(
        app,
        request_body(
            fix_at="2026-08-08T23:30:02Z",
            received_at="2026-08-08T23:30:03Z",
        ),
    )

    assert accepted.status_code == 200
    assert rejected.status_code == 409
    assert loads(rejected.body)["error"] == "stale_location"
    assert repository.state == prior


def test_storage_failure_returns_503_and_preserves_previous_location() -> None:
    repository = RecordingRepository()
    app, _, _ = application(repository)
    assert put(app, request_body()).status_code == 200
    prior = repository.state
    repository.error = ForgeMobileLocationStorageError("disk full")

    response = put(
        app,
        request_body(
            fix_at="2026-08-08T23:30:02Z",
            received_at="2026-08-08T23:30:03Z",
        ),
    )

    assert response.status_code == 503
    assert loads(response.body)["error"] == "location_persistence_unavailable"
    assert repository.state == prior


def test_received_timestamp_staleness_is_rejected_before_repository_write() -> None:
    source = StaticSpotStateSource()
    repository = RecordingRepository()
    service = ForgeMobileLocationService(
        repository,
        now=lambda: BASE_TIME + timedelta(minutes=5),
    )
    app = ForgeSpotApiApplication(source, mobile_location=service)

    response = put(app, request_body())

    assert response.status_code == 409
    assert loads(response.body)["error"] == "stale_location"
    assert repository.state is None
