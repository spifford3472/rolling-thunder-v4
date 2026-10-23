"""Integrated offline-first contact durability and reconnect acceptance tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import UUID

from rolling_thunder.contact_commit_controller import ContactCommitController
from rolling_thunder.contact_logging import ContactLoggingService
from rolling_thunder.contact_repository import ContactRepository
from rolling_thunder.contact_retry import ContactRetryRepository
from rolling_thunder.contact_sync import ContactSyncResult, ContactSyncService
from rolling_thunder.domain import (
    Contact,
    Frequency,
    RadioConnectionState,
    RadioMode,
    RadioState,
    SynchronizationState,
)
from rolling_thunder.forge_contact_sync import (
    ForgeContactSyncRepository,
    ForgeContactSyncService,
)
from rolling_thunder.ft8.coordinator import FT8QsoResult
from rolling_thunder.ft8.domain import (
    FT8Period,
    FT8PeriodParity,
    FT8QsoContext,
    FT8QsoState,
)
from rolling_thunder.ft8.logging import FT8QsoLoggingService
from rolling_thunder.home_platform import (
    ContactUploadRequest,
    ContactUploadResult,
    HomePlatformConnectionError,
)
from rolling_thunder.log_panel import ContactLogRepository, LogPanelController
from rolling_thunder.mock_home_platform import MockHomePlatformClient
from rolling_thunder.radio_polling import PollCallback
from rolling_thunder.wavelog import (
    WavelogStationLocation,
    WavelogStationTarget,
    WavelogUploadDisposition,
)

NOW = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)


class FixedClock:
    def now(self) -> datetime:
        return NOW


class NoopScheduledPoll:
    def cancel(self) -> None:
        return None


class NoopScheduler:
    def schedule_repeating(
        self,
        interval_s: float,
        callback: PollCallback,
    ) -> NoopScheduledPoll:
        del interval_s, callback
        return NoopScheduledPoll()


class HeldOfflineClient(MockHomePlatformClient):
    """Hold one upload until the test proves local work completed independently."""

    def __init__(self) -> None:
        super().__init__(clock=lambda: NOW)
        self.entered = Event()
        self.release = Event()

    def upload_contact(self, request: ContactUploadRequest) -> ContactUploadResult:
        del request
        self.entered.set()
        assert self.release.wait(timeout=2)
        raise HomePlatformConnectionError("deterministic held outage")


class FakeWavelog:
    def __init__(self) -> None:
        self.uploaded_ids: list[UUID] = []

    def verify_health_target(self) -> None:
        return None

    def resolve_station_target(self, contact: Contact) -> WavelogStationTarget:
        del contact
        return WavelogStationTarget(
            WavelogStationLocation(42, "Mobile", "mobile-uuid"),
            dynamic=False,
        )

    def upload_contact(
        self,
        contact: Contact,
        *,
        target: WavelogStationTarget,
    ) -> WavelogUploadDisposition:
        del target
        self.uploaded_ids.append(contact.contact_id)
        return WavelogUploadDisposition.IMPORTED


class LostResponseForgeClient(MockHomePlatformClient):
    """Commit remotely, then lose each first response before Pi acknowledgement."""

    def __init__(self, forge: ForgeContactSyncService) -> None:
        super().__init__(clock=lambda: NOW)
        self._forge = forge
        self._lost_ids: set[UUID] = set()

    def upload_contact(self, request: ContactUploadRequest) -> ContactUploadResult:
        result = self._forge.synchronize(request.contact)
        if request.contact.contact_id not in self._lost_ids:
            self._lost_ids.add(request.contact.contact_id)
            raise HomePlatformConnectionError("response lost after durable remote delivery")
        return result


class ForgeClient(MockHomePlatformClient):
    def __init__(self, forge: ForgeContactSyncService) -> None:
        super().__init__(clock=lambda: NOW)
        self._forge = forge

    def upload_contact(self, request: ContactUploadRequest) -> ContactUploadResult:
        return self._forge.synchronize(request.contact)


def _radio_state() -> RadioState:
    return RadioState(
        connection_state=RadioConnectionState.CONNECTED,
        frequency=Frequency(hz=14_250_000),
        mode=RadioMode.USB,
        updated_at=NOW,
    )


def _ft8_result() -> FT8QsoResult:
    period = FT8Period.from_utc(NOW)
    return FT8QsoResult(
        status=FT8QsoState.COMPLETED,
        context=FT8QsoContext(
            local_callsign="KI5VNB",
            remote_callsign="K1ABC",
            target_audio_frequency_hz=1500,
            radio_frequency_hz=14_074_000,
            radio_band="20m",
            radio_mode="USB",
            local_grid="EM79xm",
            latitude=39.5309,
            longitude=-84.0866,
            local_state="OH",
            local_cq_zone=4,
            local_itu_zone=8,
            remote_grid="FN31pr",
            tx_parity=FT8PeriodParity.ODD,
            authorized_period=period,
            authorized_utc=NOW,
            signal_report_db=-8,
            qso_id=UUID("00000000-0000-0000-0000-000000003451"),
        ),
        sent_report_db=-8,
        received_report_db=-10,
        started_utc=NOW,
        ended_utc=NOW + timedelta(seconds=75),
        terminal_reason=None,
    )


def test_ui_commit_completes_while_network_sync_future_is_held(tmp_path) -> None:
    database = tmp_path / "contacts.db"
    repository = ContactRepository(database)
    logging = ContactLoggingService(repository, FixedClock())
    logging.commit(pending_callsign="W1AW", radio_state=_radio_state())

    held_client = HeldOfflineClient()
    sync = ContactSyncService(repository, held_client, NoopScheduler())
    executor = ThreadPoolExecutor(max_workers=1)
    panel = LogPanelController(ContactLogRepository(database), sync, executor=executor)
    committed = Event()
    controller = ContactCommitController(
        logging,
        on_started=lambda _callsign: None,
        on_succeeded=lambda _callsign: committed.set(),
        on_failed=lambda message: raise_assertion(message),
    )
    try:
        assert panel.request_sync() is True
        assert held_client.entered.wait(timeout=2)

        assert controller.start_commit("K2ABC", _radio_state()) is True
        assert committed.wait(timeout=2)
        assert held_client.release.is_set() is False

        reconstructed = ContactRepository(database)
        stored = reconstructed.list_all()
        assert {contact.callsign for contact in stored} == {"K2ABC", "W1AW"}
        assert all(
            contact.synchronization_state is SynchronizationState.PENDING
            for contact in stored
        )
    finally:
        held_client.release.set()
        panel.stop()
        executor.shutdown(wait=True)


def test_outage_reconstruction_and_reconnect_do_not_duplicate_wavelog(tmp_path) -> None:
    database = tmp_path / "contacts.db"
    repository = ContactRepository(database)
    ordinary = ContactLoggingService(repository, FixedClock()).commit(
        pending_callsign="W1AW",
        radio_state=_radio_state(),
    )
    ft8 = FT8QsoLoggingService(ContactLoggingService(repository)).handle_terminal_result(
        _ft8_result()
    )
    assert ft8 is not None
    assert ft8.contact_id == _ft8_result().context.qso_id

    offline = MockHomePlatformClient(clock=lambda: NOW, available=False)
    first_sync = ContactSyncService(
        repository,
        offline,
        NoopScheduler(),
        retry_store=ContactRetryRepository(database),
        clock=lambda: NOW,
    )
    assert first_sync.synchronize_due_now() == ContactSyncResult(
        attempted=2,
        synchronized=0,
        failed=2,
    )

    reconstructed = ContactRepository(database)
    assert {
        contact.contact_id: contact.synchronization_state
        for contact in reconstructed.list_all()
    } == {
        ordinary.contact_id: SynchronizationState.FAILED,
        ft8.contact_id: SynchronizationState.FAILED,
    }
    due = NOW + timedelta(seconds=5)
    reconstructed_retries = ContactRetryRepository(database)
    assert set(reconstructed_retries.list_due_contact_ids(due, limit=10)) == {
        ordinary.contact_id,
        ft8.contact_id,
    }

    wavelog = FakeWavelog()
    forge_database = tmp_path / "forge-ledger.db"
    forge = ForgeContactSyncService(
        ForgeContactSyncRepository(forge_database),
        wavelog,
        clock=lambda: due,
    )
    lost_responses = ContactSyncService(
        reconstructed,
        LostResponseForgeClient(forge),
        NoopScheduler(),
        retry_store=reconstructed_retries,
        clock=lambda: due,
    )
    assert lost_responses.synchronize_due_now().failed == 2
    assert set(wavelog.uploaded_ids) == {ordinary.contact_id, ft8.contact_id}

    retry_time = due + timedelta(seconds=10)
    final_repository = ContactRepository(database)
    final_sync = ContactSyncService(
        final_repository,
        ForgeClient(
            ForgeContactSyncService(
                ForgeContactSyncRepository(forge_database),
                wavelog,
                clock=lambda: retry_time,
            )
        ),
        NoopScheduler(),
        retry_store=ContactRetryRepository(database),
        clock=lambda: retry_time,
    )
    assert final_sync.synchronize_due_now() == ContactSyncResult(
        attempted=2,
        synchronized=2,
        failed=0,
    )
    assert len(wavelog.uploaded_ids) == 2
    assert all(
        contact.synchronization_state is SynchronizationState.SYNCHRONIZED
        for contact in ContactRepository(database).list_all()
    )
    assert final_sync.synchronize_due_now().attempted == 0


def raise_assertion(message: str) -> None:
    raise AssertionError(message)
