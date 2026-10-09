"""Tests for the source-owned completed-QSO producer outbox."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

from rolling_thunder.completed_qso_producer import (
    CompletedQsoDeliveryState,
    CompletedQsoDeliveryWorker,
    CompletedQsoDestination,
    CompletedQsoPostDurabilityAdapter,
    CompletedQsoProducerConflict,
    CompletedQsoProducerDisposition,
    CompletedQsoProducerRepository,
)
from rolling_thunder.domain import Contact, ContactSource, RadioMode
from rolling_thunder.forge_pskreporter_orchestration import CompletedFt8QsoEvent
from rolling_thunder.ft8.performance import FT8AttemptOutcome, FT8PerformanceAttempt

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
QSO_ID = UUID("11111111-2222-4333-8444-555555555555")


def test_adapter_persists_only_a_matching_durable_event_and_replays_exactly(
    tmp_path: Path,
) -> None:
    repository = CompletedQsoProducerRepository(tmp_path / "completed-qso.sqlite3")
    adapter = CompletedQsoPostDurabilityAdapter(repository, clock=lambda: NOW)

    first = adapter.capture(_contact(), _attempt())
    replay = adapter.capture(_contact(), _attempt())

    assert first is CompletedQsoProducerDisposition.ACCEPTED
    assert replay is CompletedQsoProducerDisposition.REPLAYED
    for destination in CompletedQsoDestination:
        items = repository.list_due(destination, now_utc=NOW, limit=10)
        assert len(items) == 1
        assert items[0].event == _event()

    with pytest.raises(ValueError, match="UUID must match"):
        adapter.capture(
            _contact(),
            _attempt().model_copy(
                update={"attempt_id": UUID("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")}
            ),
        )


def test_changed_replay_fails_closed_for_both_destinations(tmp_path: Path) -> None:
    repository = CompletedQsoProducerRepository(tmp_path / "completed-qso.sqlite3")
    adapter = CompletedQsoPostDurabilityAdapter(repository, clock=lambda: NOW)
    adapter.capture(_contact(), _attempt())

    with pytest.raises(CompletedQsoProducerConflict, match="changed data"):
        adapter.capture(
            _contact().model_copy(update={"tx_power_watts": 60}),
            _attempt(),
        )

    for destination in CompletedQsoDestination:
        assert repository.state_for(QSO_ID, destination) is CompletedQsoDeliveryState.PENDING


def test_destinations_progress_and_retry_independently_after_restart(tmp_path: Path) -> None:
    database = tmp_path / "completed-qso.sqlite3"
    repository = CompletedQsoProducerRepository(database)
    CompletedQsoPostDurabilityAdapter(repository, clock=lambda: NOW).capture(
        _contact(), _attempt()
    )
    voacap = ContactSink()
    psk = EventSink(fail=True)
    worker = CompletedQsoDeliveryWorker(
        repository,
        voacap_sink=voacap,
        psk_reporter_sink=psk,
        retry_initial_delay=timedelta(seconds=5),
        clock=lambda: NOW,
    )

    result = worker.run_once()

    assert result[CompletedQsoDestination.VOACAP] == (1, 1)
    assert result[CompletedQsoDestination.PSK_REPORTER] == (1, 0)
    assert voacap.contacts == [_contact()]
    assert psk.events == [_event()]
    assert repository.state_for(QSO_ID, CompletedQsoDestination.VOACAP) is (
        CompletedQsoDeliveryState.DELIVERED
    )
    assert repository.state_for(QSO_ID, CompletedQsoDestination.PSK_REPORTER) is (
        CompletedQsoDeliveryState.RETRY
    )

    restarted_repository = CompletedQsoProducerRepository(database)
    recovered_psk = EventSink()
    before_due = CompletedQsoDeliveryWorker(
        restarted_repository,
        voacap_sink=ContactSink(),
        psk_reporter_sink=recovered_psk,
        clock=lambda: NOW + timedelta(seconds=4),
    ).run_once()
    after_due = CompletedQsoDeliveryWorker(
        restarted_repository,
        voacap_sink=ContactSink(),
        psk_reporter_sink=recovered_psk,
        clock=lambda: NOW + timedelta(seconds=5),
    ).run_once()

    assert before_due[CompletedQsoDestination.VOACAP] == (0, 0)
    assert before_due[CompletedQsoDestination.PSK_REPORTER] == (0, 0)
    assert after_due[CompletedQsoDestination.VOACAP] == (0, 0)
    assert after_due[CompletedQsoDestination.PSK_REPORTER] == (1, 1)
    assert recovered_psk.events == [_event()]
    assert restarted_repository.state_for(
        QSO_ID, CompletedQsoDestination.PSK_REPORTER
    ) is CompletedQsoDeliveryState.DELIVERED


class ContactSink:
    def __init__(self) -> None:
        self.contacts: list[Contact] = []

    def enqueue(self, contact: Contact) -> None:
        self.contacts.append(contact)


class EventSink:
    def __init__(self, *, fail: bool = False) -> None:
        self.events: list[CompletedFt8QsoEvent] = []
        self._fail = fail

    def enqueue(self, event: CompletedFt8QsoEvent) -> None:
        self.events.append(event)
        if self._fail:
            raise OSError("private Forge service unavailable")


def _event() -> CompletedFt8QsoEvent:
    return CompletedFt8QsoEvent(contact=_contact(), terminal_attempt=_attempt())


def _contact() -> Contact:
    return Contact(
        contact_id=QSO_ID,
        callsign="KC1OXG",
        frequency_hz=14_074_000,
        mode=RadioMode.FT8,
        started_at=NOW,
        rst_sent="-10",
        rst_received="-12",
        grid="FN31pr",
        my_grid="EM79xp",
        source=ContactSource.FT8,
        tx_power_watts=55,
    )


def _attempt() -> FT8PerformanceAttempt:
    return FT8PerformanceAttempt(
        attempt_id=QSO_ID,
        callsign="KC1OXG",
        outcome=FT8AttemptOutcome.COMPLETED,
        success=True,
        terminal_state="completed",
        terminal_reason=None,
        started_at_utc=NOW,
        ended_at_utc=NOW + timedelta(seconds=75),
        utc_date=NOW.date(),
        band="20m",
        dial_frequency_hz=14_074_000,
        tx_power_target_watts=55,
        tx_power_start_watts=55,
        tx_power_end_watts=55,
        tx_power_max_watts=55,
        sent_report_db=-10,
        received_report_db=-12,
        local_grid="EM79xp",
        remote_grid="FN31pr",
        audio_frequency_hz=1500,
        attempt_count=3,
        last_qso_state="completed",
    )
