"""Tests for the private Forge Home Platform compatible contact API."""

from __future__ import annotations

from datetime import UTC, datetime
from json import dumps, loads
from pathlib import Path

from rolling_thunder.domain import Contact, RadioMode
from rolling_thunder.forge_contact_sync import ForgeContactSyncRepository, ForgeContactSyncService
from rolling_thunder.forge_contact_sync_api import ForgeContactSyncApiApplication
from rolling_thunder.wavelog import WavelogStationLocation, WavelogUploadDisposition


class FakeWavelog:
    def __init__(self) -> None:
        self.upload_count = 0
        self.contacts: list[Contact] = []

    def resolve_station_location(self, *, refresh: bool = False) -> WavelogStationLocation:
        del refresh
        return WavelogStationLocation(42, "Mobile", "mobile")

    def upload_contact(self, contact: Contact) -> WavelogUploadDisposition:
        self.contacts.append(contact)
        self.upload_count += 1
        return WavelogUploadDisposition.IMPORTED


def contact() -> Contact:
    return Contact(
        contact_id="11111111-2222-3333-4444-555555555555",
        callsign="W1AW",
        frequency_hz=14_250_000,
        mode=RadioMode.USB,
        started_at=datetime(2026, 8, 12, 15, 0, tzinfo=UTC),
        rst_sent="59",
        rst_received="59",
    )


def app(tmp_path: Path) -> tuple[ForgeContactSyncApiApplication, FakeWavelog]:
    wavelog = FakeWavelog()
    service = ForgeContactSyncService(
        ForgeContactSyncRepository(tmp_path / "ledger.db"),
        wavelog,  # type: ignore[arg-type]
    )
    return ForgeContactSyncApiApplication(service), wavelog


def upload(
    application: ForgeContactSyncApiApplication,
    qso: Contact,
    *,
    key: str | None = None,
):
    headers = {"Content-Type": "application/json"}
    if key is not None:
        headers["Idempotency-Key"] = key
    return application.handle(
        "POST",
        "/contacts",
        headers=headers,
        body=qso.model_dump_json().encode(),
    )


def test_contact_api_requires_matching_stable_uuid_idempotency_key(tmp_path: Path) -> None:
    application, wavelog = app(tmp_path)
    qso = contact()

    missing = upload(application, qso)
    mismatched = upload(application, qso, key="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

    assert missing.status_code == 400
    assert loads(missing.body)["error"] == "missing_idempotency_key"
    assert mismatched.status_code == 409
    assert loads(mismatched.body)["error"] == "idempotency_key_mismatch"
    assert wavelog.upload_count == 0


def test_repeated_contact_upload_returns_already_exists_without_second_wavelog_write(
    tmp_path: Path,
) -> None:
    application, wavelog = app(tmp_path)
    qso = contact()
    key = str(qso.contact_id)

    first = upload(application, qso, key=key)
    second = upload(application, qso, key=key)

    assert first.status_code == 200
    assert loads(first.body)["disposition"] == "accepted"
    assert second.status_code == 200
    assert loads(second.body)["disposition"] == "already_exists"
    assert wavelog.upload_count == 1


def test_health_contract_is_compatible_with_existing_pi_client(tmp_path: Path) -> None:
    application, _ = app(tmp_path)

    response = application.handle("GET", "/health")

    assert response.status_code == 200
    payload = loads(response.body)
    assert payload["availability"] == "available"
    assert payload["checked_at"].endswith("Z")


def test_malformed_or_oversized_contact_body_is_rejected_before_wavelog(tmp_path: Path) -> None:
    application, wavelog = app(tmp_path)

    malformed = application.handle(
        "POST",
        "/contacts",
        headers={"Content-Type": "application/json", "Idempotency-Key": str(contact().contact_id)},
        body=b"{not-json",
    )
    oversized = application.handle(
        "POST",
        "/contacts",
        headers={"Content-Type": "application/json", "Idempotency-Key": str(contact().contact_id)},
        body=dumps({"notes": "x" * 40_000}).encode(),
    )

    assert malformed.status_code == 400
    assert oversized.status_code == 413
    assert wavelog.upload_count == 0


def test_coordinate_contact_is_accepted_and_preserved(tmp_path: Path) -> None:
    application, wavelog = app(tmp_path)
    qso = contact().model_copy(update={"my_latitude": 39.5309, "my_longitude": -84.0866})
    response = upload(application, qso, key=str(qso.contact_id))
    assert response.status_code == 200
    assert wavelog.contacts == [qso]
    assert wavelog.resolve_station_location().name == "Mobile"


def test_legacy_contact_body_without_coordinates_is_accepted(tmp_path: Path) -> None:
    application, wavelog = app(tmp_path)
    qso = contact()
    payload = qso.model_dump(mode="json")
    del payload["my_latitude"]
    del payload["my_longitude"]
    response = application.handle(
        "POST",
        "/contacts",
        headers={"Content-Type": "application/json", "Idempotency-Key": str(qso.contact_id)},
        body=dumps(payload).encode(),
    )
    assert response.status_code == 200
    assert wavelog.contacts == [qso]
