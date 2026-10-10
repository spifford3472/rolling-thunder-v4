"""Isolation tests: confirmed primary QSO sync must survive snapshot faults."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from rolling_thunder.domain import Contact, ContactSource, RadioMode
from rolling_thunder.forge_contact_snapshots import (
    ContactSnapshotError,
    ForgeContactSnapshotRepository,
)
from rolling_thunder.forge_contact_sync import ForgeContactSyncRepository, ForgeContactSyncService
from rolling_thunder.home_platform import ContactUploadDisposition
from rolling_thunder.wavelog import (
    WavelogStationLocation,
    WavelogStationTarget,
    WavelogUploadDisposition,
)


def _contact() -> Contact:
    return Contact(
        contact_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        callsign="K1ABC",
        frequency_hz=14074000,
        mode=RadioMode.FT8,
        source=ContactSource.FT8,
        started_at=datetime(2026, 10, 9, 13, tzinfo=UTC),
        rst_sent="-09",
        rst_received="-12",
    )


class WavelogStub:
    uploads = 0

    def resolve_station_target(self, contact: Contact) -> WavelogStationTarget:
        return WavelogStationTarget(
            WavelogStationLocation(1, "Mobile", "mobile-uuid"), dynamic=False
        )

    def upload_contact(
        self, contact: Contact, *, target: WavelogStationTarget
    ) -> WavelogUploadDisposition:
        self.uploads += 1
        return WavelogUploadDisposition.IMPORTED

    def verify_health_target(self) -> None:
        return None


def test_snapshot_is_readable_and_does_not_repeat_upload(tmp_path: Path) -> None:
    snapshots = ForgeContactSnapshotRepository(tmp_path / "snapshots.db")
    ledger = ForgeContactSyncRepository(tmp_path / "ledger.db")
    wavelog = WavelogStub()
    service = ForgeContactSyncService(ledger, wavelog, contact_snapshots=snapshots)
    first = service.synchronize(_contact())
    second = service.synchronize(_contact())
    assert first.disposition is ContactUploadDisposition.ACCEPTED
    assert second.disposition is ContactUploadDisposition.ALREADY_EXISTS
    assert wavelog.uploads == 1
    assert snapshots.read(_contact().contact_id) == _contact()


def test_snapshot_conflict_preserves_first_payload(tmp_path: Path) -> None:
    snapshots = ForgeContactSnapshotRepository(tmp_path / "snapshots.db")
    snapshots.record(_contact())
    with pytest.raises(ContactSnapshotError, match="conflict"):
        snapshots.record(_contact().model_copy(update={"rst_received": "-21"}))
    assert snapshots.read(_contact().contact_id) == _contact()


def test_broken_optional_snapshot_never_fails_primary_sync(tmp_path: Path) -> None:
    class BrokenSnapshots:
        def record(self, contact: Contact) -> None:
            raise ContactSnapshotError("simulated storage offline")

    ledger = ForgeContactSyncRepository(tmp_path / "ledger.db")
    wavelog = WavelogStub()
    service = ForgeContactSyncService(ledger, wavelog, contact_snapshots=BrokenSnapshots())  # type: ignore[arg-type]
    assert service.synchronize(_contact()).disposition is ContactUploadDisposition.ACCEPTED
    assert wavelog.uploads == 1


def test_failed_wavelog_upload_never_snapshots(tmp_path: Path) -> None:
    class FailedUpload(WavelogStub):
        def upload_contact(
            self, contact: Contact, *, target: WavelogStationTarget
        ) -> WavelogUploadDisposition:
            raise RuntimeError("provider unavailable")

    snapshots = ForgeContactSnapshotRepository(tmp_path / "snapshots.db")
    service = ForgeContactSyncService(
        ForgeContactSyncRepository(tmp_path / "ledger.db"),
        FailedUpload(),
        contact_snapshots=snapshots,
    )
    with pytest.raises(RuntimeError, match="provider unavailable"):
        service.synchronize(_contact())
    assert snapshots.read(_contact().contact_id) is None


def test_non_ft8_contact_does_not_enter_psk_snapshot(tmp_path: Path) -> None:
    snapshots = ForgeContactSnapshotRepository(tmp_path / "snapshots.db")
    service = ForgeContactSyncService(
        ForgeContactSyncRepository(tmp_path / "ledger.db"),
        WavelogStub(),
        contact_snapshots=snapshots,
    )
    voice = _contact().model_copy(update={"mode": RadioMode.USB, "source": ContactSource.UNKNOWN})
    assert service.synchronize(voice).disposition is ContactUploadDisposition.ACCEPTED
    assert snapshots.read(voice.contact_id) is None
