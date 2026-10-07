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
from rolling_thunder.wavelog import (
    WavelogStationLocation,
    WavelogStationTarget,
    WavelogUploadDisposition,
)


class FakeWavelog:
    def __init__(self) -> None:
        self.location = WavelogStationLocation(42, "Mobile", "mobile-uuid")
        self.dispositions: list[WavelogUploadDisposition] = []
        self.upload_count = 0
        self.targets: list[WavelogStationTarget] = []
        self.contacts: list[Contact] = []

    def verify_health_target(self) -> None:
        return None

    def resolve_station_target(self, contact: Contact) -> WavelogStationTarget:
        del contact
        return WavelogStationTarget(self.location, dynamic=False)

    def upload_contact(
        self,
        contact: Contact,
        *,
        target: WavelogStationTarget,
    ) -> WavelogUploadDisposition:
        self.contacts.append(contact)
        self.targets.append(target)
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
    return ForgeContactSyncService(ForgeContactSyncRepository(path), wavelog)


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
    service = ForgeContactSyncService(repository, wavelog)

    result = service.synchronize(qso)
    repeated = service.synchronize(qso)

    assert result.disposition is ContactUploadDisposition.ALREADY_EXISTS
    assert repeated.disposition is ContactUploadDisposition.ALREADY_EXISTS
    assert wavelog.upload_count == 1
    assert [target.location.station_id for target in wavelog.targets] == [42]


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


@pytest.mark.parametrize(
    "updates",
    [
        {},
        {"callsign": "ZS6BKW"},
        {"pota_reference": "US-0732"},
        {"mode": RadioMode.FT8, "frequency_hz": 14_074_000, "rst_sent": "-10"},
        {"mode": RadioMode.DMR, "frequency_hz": 446_500_000},
    ],
    ids=["ordinary", "dx", "pota", "ft8", "dmr"],
)
def test_contact_kinds_share_one_station_routing_and_upload_boundary(
    tmp_path: Path,
    updates: dict[str, object],
) -> None:
    wavelog = FakeWavelog()
    service = build_service(tmp_path / "ledger.db", wavelog)
    qso = Contact.model_validate(
        {
            **contact().model_dump(mode="python"),
            "contact_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            **updates,
        }
    )

    result = service.synchronize(qso)

    assert result.disposition is ContactUploadDisposition.ACCEPTED
    assert wavelog.upload_count == 1
    assert [target.location.station_id for target in wavelog.targets] == [42]
