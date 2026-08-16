"""Tests for durable Forge-side contact idempotency."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from rolling_thunder.domain import Contact, RadioMode
from rolling_thunder.forge_contact_sync import (
    ForgeContactPayloadConflictError,
    ForgeContactSyncRepository,
    ForgeContactSyncService,
)
from rolling_thunder.home_platform import ContactUploadDisposition
from rolling_thunder.wavelog import WavelogStationLocation, WavelogUploadDisposition


class FakeWavelog:
    def __init__(self) -> None:
        self.location = WavelogStationLocation(42, "Mobile", "mobile-uuid")
        self.dispositions: list[WavelogUploadDisposition] = []
        self.upload_count = 0

    def resolve_station_location(self, *, refresh: bool = False) -> WavelogStationLocation:
        del refresh
        return self.location

    def upload_contact(self, contact: Contact) -> WavelogUploadDisposition:
        del contact
        self.upload_count += 1
        if self.dispositions:
            return self.dispositions.pop(0)
        return WavelogUploadDisposition.IMPORTED


def contact(*, notes: str | None = None) -> Contact:
    return Contact(
        contact_id="11111111-2222-3333-4444-555555555555",
        callsign="W1AW",
        frequency_hz=14_250_000,
        mode=RadioMode.USB,
        started_at=datetime(2026, 8, 12, 15, 0, tzinfo=UTC),
        rst_sent="59",
        rst_received="59",
        notes=notes,
    )


def build_service(path: Path, wavelog: FakeWavelog) -> ForgeContactSyncService:
    return ForgeContactSyncService(ForgeContactSyncRepository(path), wavelog)  # type: ignore[arg-type]


def test_successful_contact_is_not_replayed_after_forge_restart(tmp_path: Path) -> None:
    database = tmp_path / "ledger.db"
    wavelog = FakeWavelog()
    first = build_service(database, wavelog)

    first_result = first.synchronize(contact())
    restarted = build_service(database, wavelog)
    second_result = restarted.synchronize(contact())

    assert first_result.disposition is ContactUploadDisposition.ACCEPTED
    assert second_result.disposition is ContactUploadDisposition.ALREADY_EXISTS
    assert wavelog.upload_count == 1


def test_remote_duplicate_after_uncertain_prior_result_is_marked_synchronized(
    tmp_path: Path,
) -> None:
    database = tmp_path / "ledger.db"
    repository = ForgeContactSyncRepository(database)
    wavelog = FakeWavelog()
    wavelog.dispositions = [WavelogUploadDisposition.DUPLICATE]
    qso = contact()

    # Simulate the durable pre-write claim that exists if Forge/Wavelog lost the
    # successful response before Forge could mark the ledger synchronized.
    from rolling_thunder.forge_contact_sync import _remote_payload_sha256

    repository.claim(
        qso.contact_id,
        payload_sha256=_remote_payload_sha256(qso, station_profile_id=42),
        station_profile_id=42,
    )
    service = ForgeContactSyncService(repository, wavelog)  # type: ignore[arg-type]

    result = service.synchronize(qso)
    repeated = service.synchronize(qso)

    assert result.disposition is ContactUploadDisposition.ALREADY_EXISTS
    assert repeated.disposition is ContactUploadDisposition.ALREADY_EXISTS
    assert wavelog.upload_count == 1


def test_same_uuid_with_changed_qso_payload_is_rejected(tmp_path: Path) -> None:
    database = tmp_path / "ledger.db"
    wavelog = FakeWavelog()
    service = build_service(database, wavelog)
    service.synchronize(contact())

    with pytest.raises(ForgeContactPayloadConflictError):
        service.synchronize(contact(notes="different remote data"))

    assert wavelog.upload_count == 1


def test_station_location_change_for_existing_uuid_is_rejected(tmp_path: Path) -> None:
    database = tmp_path / "ledger.db"
    wavelog = FakeWavelog()
    service = build_service(database, wavelog)
    service.synchronize(contact())
    wavelog.location = WavelogStationLocation(99, "Mobile", "different-profile")

    with pytest.raises(ForgeContactPayloadConflictError):
        service.synchronize(contact())

    assert wavelog.upload_count == 1
