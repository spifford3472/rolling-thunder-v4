"""Tests for the private Forge FT8 performance API endpoint."""

import logging
from datetime import UTC, date, datetime, timedelta
from json import loads
from pathlib import Path
from uuid import UUID

from rolling_thunder.domain import Contact
from rolling_thunder.forge_contact_sync import ForgeContactSyncRepository, ForgeContactSyncService
from rolling_thunder.forge_contact_sync_api import ForgeContactSyncApiApplication
from rolling_thunder.forge_ft8_performance import (
    ForgeFT8PerformanceRepository,
    ForgeFT8PerformanceService,
)
from rolling_thunder.ft8.performance import FT8AttemptOutcome, FT8PerformanceAttempt
from rolling_thunder.wavelog import (
    WavelogStationLocation,
    WavelogStationTarget,
    WavelogUploadDisposition,
)


class FakeWavelog:
    def __init__(self) -> None:
        self.upload_count = 0

    def verify_health_target(self) -> None:
        return None

    def resolve_station_target(self, contact: Contact) -> WavelogStationTarget:
        del contact
        return WavelogStationTarget(
            WavelogStationLocation(42, "Mobile", "mobile"),
            dynamic=False,
        )

    def upload_contact(
        self,
        contact: Contact,
        *,
        target: WavelogStationTarget,
    ) -> WavelogUploadDisposition:
        del contact
        del target
        self.upload_count += 1
        return WavelogUploadDisposition.IMPORTED


_DEFAULT_ATTEMPT_ID = UUID("00000000-0000-0000-0000-000000000401")

def _attempt(
    *,
    attempt_id: UUID = _DEFAULT_ATTEMPT_ID,
) -> FT8PerformanceAttempt:
    started = datetime(2026, 10, 2, 20, 0, tzinfo=UTC)
    return FT8PerformanceAttempt(
        attempt_id=attempt_id,
        callsign="K1ABC",
        outcome=FT8AttemptOutcome.ABORTED,
        success=False,
        terminal_state="aborted",
        terminal_reason="operator abort",
        started_at_utc=started,
        ended_at_utc=started + timedelta(seconds=30),
        utc_date=date(2026, 10, 2),
        band="20m",
        dial_frequency_hz=14_074_000,
        local_grid="EM79xm",
        local_latitude=39.25,
        local_longitude=-84.55,
        remote_grid="FN31pr",
        distance_km=1000.0,
        audio_frequency_hz=1500,
    )

def _app(tmp_path: Path) -> tuple[ForgeContactSyncApiApplication, FakeWavelog]:
    database = tmp_path / "forge.db"
    wavelog = FakeWavelog()
    contact_service = ForgeContactSyncService(
        ForgeContactSyncRepository(database),
        wavelog,  # type: ignore[arg-type]
    )
    performance_service = ForgeFT8PerformanceService(
        ForgeFT8PerformanceRepository(database)
    )
    return (
        ForgeContactSyncApiApplication(
            contact_service,
            ft8_performance_service=performance_service,
        ),
        wavelog,
    )

def _upload(
    application: ForgeContactSyncApiApplication,
    attempt: FT8PerformanceAttempt,
    *,
    key: str | None,
):
    headers = {"Content-Type": "application/json"}
    if key is not None:
        headers["Idempotency-Key"] = key
    return application.handle(
        "POST",
        "/ft8-performance",
        headers=headers,
        body=attempt.model_dump_json().encode(),
    )

def test_performance_upload_is_idempotent_and_never_calls_wavelog(tmp_path: Path) -> None:
    application, wavelog = _app(tmp_path)
    attempt = _attempt()
    key = str(attempt.attempt_id)

    first = _upload(application, attempt, key=key)
    second = _upload(application, attempt, key=key)

    assert first.status_code == 200
    assert loads(first.body)["disposition"] == "accepted"
    assert second.status_code == 200
    assert loads(second.body)["disposition"] == "already_exists"
    assert wavelog.upload_count == 0


def test_performance_upload_requires_matching_attempt_id(tmp_path: Path) -> None:
    application, wavelog = _app(tmp_path)
    attempt = _attempt()

    missing = _upload(application, attempt, key=None)
    mismatch = _upload(
        application,
        attempt,
        key="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    )

    assert missing.status_code == 400
    assert loads(missing.body)["error"] == "missing_idempotency_key"
    assert mismatch.status_code == 409
    assert loads(mismatch.body)["error"] == "idempotency_key_mismatch"
    assert wavelog.upload_count == 0


def test_invalid_performance_payload_is_logged_for_diagnosis(
    tmp_path: Path,
    caplog,
) -> None:
    application, _ = _app(tmp_path)
    caplog.set_level(logging.WARNING, logger="rolling_thunder.forge_contact_sync")

    response = application.handle(
        "POST",
        "/ft8-performance",
        headers={
            "Content-Type": "application/json",
            "Idempotency-Key": str(_DEFAULT_ATTEMPT_ID),
        },
        body=(
            b'{"attempt_id":"00000000-0000-0000-0000-000000000401",'
            b'"callsign":"K1ABC"}'
        ),
    )

    assert response.status_code == 422
    payload = loads(response.body)
    assert payload["error"] == "invalid_ft8_performance"
    assert "Invalid FT8 performance field outcome" in payload["message"]
    assert "Rejected FT8 performance upload: Invalid FT8 performance field outcome" in caplog.text


def test_performance_endpoint_is_unavailable_when_not_composed(tmp_path: Path) -> None:
    wavelog = FakeWavelog()
    service = ForgeContactSyncService(
        ForgeContactSyncRepository(tmp_path / "forge.db"),
        wavelog,  # type: ignore[arg-type]
    )
    application = ForgeContactSyncApiApplication(service)
    attempt = _attempt()

    response = _upload(application, attempt, key=str(attempt.attempt_id))

    assert response.status_code == 503
    assert loads(response.body)["error"] == "ft8_performance_unavailable"
    assert wavelog.upload_count == 0


def test_performance_changed_replay_returns_conflict(tmp_path: Path) -> None:
    application, _ = _app(tmp_path)
    attempt = _attempt()
    key = str(attempt.attempt_id)
    assert _upload(application, attempt, key=key).status_code == 200

    changed = attempt.model_copy(update={"callsign": "K2XYZ"})
    conflict = _upload(application, changed, key=key)

    assert conflict.status_code == 409
    assert loads(conflict.body)["error"] == "idempotency_conflict"
