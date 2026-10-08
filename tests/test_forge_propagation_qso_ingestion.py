"""Offline tests for asynchronous completed-QSO propagation ingestion."""

import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from rolling_thunder.domain import Contact, ContactSource, RadioMode
from rolling_thunder.forge_propagation_history import (
    ForgePropagationHistoryRepository,
    VoacapPrediction,
)
from rolling_thunder.forge_propagation_qso_ingestion import (
    CompletedQsoCorrelationWorker,
    CompletedQsoEnqueueResult,
    CompletedQsoIdempotencyConflict,
    CompletedQsoIngestionError,
    CompletedQsoIngestionRepository,
    CompletedQsoJobState,
    VoacapCompletedQsoCorrelator,
    VoacapCorrelationDisposition,
)

CONTACT_ID = UUID("11111111-2222-4333-8444-555555555555")
NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


def test_enqueue_is_network_free_idempotent_and_preserves_frozen_qso(
    tmp_path: Path,
) -> None:
    repository = CompletedQsoIngestionRepository(tmp_path / "ingestion.sqlite3")
    contact = _contact()

    assert repository.enqueue(contact, queued_at_utc=NOW) is CompletedQsoEnqueueResult.ACCEPTED
    assert repository.enqueue(contact, queued_at_utc=NOW) is CompletedQsoEnqueueResult.REPLAYED

    snapshot = repository.read(CONTACT_ID)
    assert snapshot is not None
    assert snapshot.contact == contact
    assert snapshot.contact.contact_id == CONTACT_ID
    assert snapshot.contact.started_at == datetime(2026, 10, 7, 11, 2, 3, tzinfo=UTC)
    assert snapshot.contact.my_grid6 == "EM79xp"
    assert snapshot.contact.grid == "FN31pr"
    assert snapshot.contact.my_latitude == 39.1
    assert snapshot.contact.my_longitude == -84.5
    assert snapshot.contact.mode is RadioMode.FT8
    assert snapshot.contact.frequency_hz == 14_074_000
    assert snapshot.contact.tx_power_watts == 55
    assert snapshot.state is CompletedQsoJobState.PENDING
    assert snapshot.attempt_count == 0


@pytest.mark.parametrize(
    "changed",
    [
        {"my_grid": "EM79xx"},
        {"grid": "FN32aa"},
        {"tx_power_watts": 60},
        {"frequency_hz": 7_074_000},
        {"mode": RadioMode.USB},
    ],
)
def test_same_uuid_with_changed_qso_fails_closed(
    tmp_path: Path, changed: dict[str, object]
) -> None:
    repository = CompletedQsoIngestionRepository(tmp_path / "ingestion.sqlite3")
    repository.enqueue(_contact(), queued_at_utc=NOW)

    with pytest.raises(CompletedQsoIdempotencyConflict, match=str(CONTACT_ID)):
        repository.enqueue(_contact().model_copy(update=changed), queued_at_utc=NOW)


def test_claim_is_bounded_exclusive_and_reclaims_only_expired_lease(tmp_path: Path) -> None:
    repository = CompletedQsoIngestionRepository(tmp_path / "ingestion.sqlite3")
    first = _contact()
    second = _contact(contact_id=uuid4(), callsign="W1AW")
    repository.enqueue(first, queued_at_utc=NOW)
    repository.enqueue(second, queued_at_utc=NOW + timedelta(seconds=1))

    claimed = repository.claim_due(
        now_utc=NOW,
        limit=1,
        lease_duration=timedelta(minutes=5),
        worker_identity="worker-a",
    )

    assert len(claimed) == 1
    assert claimed[0].contact.contact_id == first.contact_id
    assert repository.claim_due(
        now_utc=NOW + timedelta(minutes=4),
        limit=1,
        lease_duration=timedelta(minutes=5),
        worker_identity="worker-b",
    )[0].contact.contact_id == second.contact_id
    assert repository.claim_due(
        now_utc=NOW + timedelta(minutes=4),
        limit=1,
        lease_duration=timedelta(minutes=5),
        worker_identity="worker-b",
    ) == ()

    active = repository.read(first.contact_id)
    assert active is not None
    assert active.worker_identity == "worker-a"
    assert active.leased_until_utc == NOW + timedelta(minutes=5)

    reclaimed = repository.claim_due(
        now_utc=NOW + timedelta(minutes=5),
        limit=1,
        lease_duration=timedelta(minutes=5),
        worker_identity="worker-b",
    )
    assert reclaimed[0].contact.contact_id == first.contact_id
    assert reclaimed[0].attempt_count == 2
    with pytest.raises(CompletedQsoIngestionError, match="stale"):
        repository.mark_completed(claimed[0], completed_at_utc=NOW)


def test_worker_isolates_failures_retries_and_never_reprocesses_completed(
    tmp_path: Path,
) -> None:
    repository = CompletedQsoIngestionRepository(
        tmp_path / "ingestion.sqlite3",
        retry_base=timedelta(seconds=30),
        retry_max=timedelta(minutes=1),
    )
    failed = _contact()
    successful = _contact(contact_id=uuid4(), callsign="W1AW")
    repository.enqueue(failed, queued_at_utc=NOW)
    repository.enqueue(successful, queued_at_utc=NOW)
    correlator = SelectiveCorrelator(failed.contact_id)
    worker = CompletedQsoCorrelationWorker(
        repository, correlator, worker_identity="worker-a", batch_limit=2
    )

    results = worker.run_due(now_utc=NOW)

    assert {result.contact_id for result in results} == {
        failed.contact_id,
        successful.contact_id,
    }
    assert repository.read(failed.contact_id).state is CompletedQsoJobState.RETRY  # type: ignore[union-attr]
    assert repository.read(successful.contact_id).state is CompletedQsoJobState.COMPLETED  # type: ignore[union-attr]
    assert worker.run_due(now_utc=NOW + timedelta(seconds=29)) == ()
    retry = worker.run_due(now_utc=NOW + timedelta(seconds=30))
    assert retry[0].contact_id == failed.contact_id
    assert retry[0].disposition == "stored"
    assert repository.read(failed.contact_id).state is CompletedQsoJobState.COMPLETED  # type: ignore[union-attr]
    assert worker.run_due(now_utc=NOW + timedelta(hours=1)) == ()
    assert correlator.calls.count(successful.contact_id) == 1


def test_failures_dead_letter_after_configured_attempts(tmp_path: Path) -> None:
    repository = CompletedQsoIngestionRepository(
        tmp_path / "ingestion.sqlite3",
        max_attempts=2,
        retry_base=timedelta(seconds=1),
        retry_max=timedelta(seconds=1),
    )
    contact = _contact()
    repository.enqueue(contact, queued_at_utc=NOW)
    worker = CompletedQsoCorrelationWorker(
        repository,
        AlwaysFailingCorrelator(),
        worker_identity="worker-a",
        batch_limit=1,
    )

    assert worker.run_due(now_utc=NOW)[0].disposition == "retry"
    assert worker.run_due(now_utc=NOW + timedelta(seconds=1))[0].disposition == "dead_letter"
    snapshot = repository.read(contact.contact_id)
    assert snapshot is not None
    assert snapshot.state is CompletedQsoJobState.DEAD_LETTER
    assert snapshot.attempt_count == 2
    assert snapshot.last_error == "VOACAP unavailable"
    assert worker.run_due(now_utc=NOW + timedelta(days=1)) == ()


def test_expired_final_attempt_dead_letters_without_extra_provider_call(
    tmp_path: Path,
) -> None:
    repository = CompletedQsoIngestionRepository(
        tmp_path / "ingestion.sqlite3", max_attempts=1
    )
    contact = _contact()
    repository.enqueue(contact, queued_at_utc=NOW)
    repository.claim_due(
        now_utc=NOW,
        limit=1,
        lease_duration=timedelta(minutes=1),
        worker_identity="crashed-worker",
    )

    assert repository.claim_due(
        now_utc=NOW + timedelta(minutes=1),
        limit=1,
        lease_duration=timedelta(minutes=1),
        worker_identity="replacement-worker",
    ) == ()
    snapshot = repository.read(contact.contact_id)
    assert snapshot is not None
    assert snapshot.state is CompletedQsoJobState.DEAD_LETTER
    assert snapshot.attempt_count == 1
    assert snapshot.last_error == "lease expired after final permitted attempt"


def test_repository_restart_keeps_due_and_completed_state(tmp_path: Path) -> None:
    database = tmp_path / "ingestion.sqlite3"
    contact = _contact()
    repository = CompletedQsoIngestionRepository(database)
    repository.enqueue(contact, queued_at_utc=NOW)
    restarted = CompletedQsoIngestionRepository(database)
    lease = restarted.claim_due(
        now_utc=NOW,
        limit=1,
        lease_duration=timedelta(minutes=5),
        worker_identity="worker-after-restart",
    )[0]
    restarted.mark_completed(lease, completed_at_utc=NOW)

    final = CompletedQsoIngestionRepository(database).read(contact.contact_id)
    assert final is not None
    assert final.state is CompletedQsoJobState.COMPLETED
    assert final.completed_at_utc == NOW
    assert final.worker_identity is None
    assert final.leased_until_utc is None


def test_queue_observation_is_read_only_and_reports_due_and_terminal_counts(
    tmp_path: Path,
) -> None:
    repository = CompletedQsoIngestionRepository(tmp_path / "ingestion.sqlite3")
    contact = _contact()
    repository.enqueue(contact, queued_at_utc=NOW)

    initial = repository.observe(now_utc=NOW)

    assert initial.pending_count == 1
    assert initial.due_count == 1
    assert initial.oldest_queued_at_utc == NOW
    assert initial.next_due_at_utc == NOW
    assert repository.read(contact.contact_id).attempt_count == 0  # type: ignore[union-attr]


def test_inbox_schema_v2_coexists_with_propagation_history_schema_v3(
    tmp_path: Path,
) -> None:
    database = tmp_path / "propagation.sqlite3"
    ForgePropagationHistoryRepository(database)
    ingestion = CompletedQsoIngestionRepository(database)
    ingestion.enqueue(_contact(), queued_at_utc=NOW)

    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT schema_version FROM propagation_schema_metadata"
        ).fetchone() == (3,)
        assert connection.execute(
            "SELECT schema_version FROM qso_ingestion_schema_metadata"
        ).fetchone() == (2,)

    assert ingestion.read(CONTACT_ID) is not None


def test_inbox_schema_v1_migrates_additively_and_preserves_pending_qso(
    tmp_path: Path,
) -> None:
    database = tmp_path / "ingestion-v1.sqlite3"
    contact = _contact()
    payload = contact.model_dump_json()
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE qso_ingestion_schema_metadata (
                singleton_id INTEGER PRIMARY KEY CHECK(singleton_id=1),
                schema_version INTEGER NOT NULL
            );
            INSERT INTO qso_ingestion_schema_metadata VALUES (1, 1);
            CREATE TABLE completed_qso_ingestion (
                contact_id TEXT PRIMARY KEY,
                payload_sha256 TEXT NOT NULL,
                contact_json TEXT NOT NULL,
                state TEXT NOT NULL,
                attempt_count INTEGER NOT NULL,
                queued_at_utc TEXT NOT NULL,
                next_attempt_at_utc TEXT NOT NULL,
                lease_token TEXT,
                leased_until_utc TEXT,
                completed_at_utc TEXT,
                last_error TEXT
            );
            """
        )
        connection.execute(
            "INSERT INTO completed_qso_ingestion VALUES "
            "(?, '', ?, 'pending', 0, ?, ?, NULL, NULL, NULL, NULL)",
            (str(contact.contact_id), payload, "2026-10-07T12:00:00Z", "2026-10-07T12:00:00Z"),
        )

    repository = CompletedQsoIngestionRepository(database)
    snapshot = repository.read(contact.contact_id)

    assert snapshot is not None
    assert snapshot.contact == contact
    assert snapshot.worker_identity is None
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT schema_version FROM qso_ingestion_schema_metadata"
        ).fetchone() == (2,)
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(completed_qso_ingestion)")
        }
    assert "worker_identity" in columns


def test_voacap_correlator_archives_qso_and_preserves_raw_provenance() -> None:
    contact = _contact()
    history = HistoryFake()
    prediction = VoacapPrediction(
        contact_id=contact.contact_id,
        captured_at_utc=NOW,
        request_json={
            "tx_grid": "EM79xp",
            "rx_grid": "FN31pr",
            "bands_m": [20],
            "power_watts": 55,
            "mode": "FT8",
            "timezone": "UTC",
        },
        service_version="2.4.1",
        response_json={"analysis": {"best_band_by_hour": []}, "raw": "retained"},
    )
    client = ClientFake(prediction)

    result = VoacapCompletedQsoCorrelator(history, client).correlate(contact)

    assert result is VoacapCorrelationDisposition.STORED
    assert client.contacts == [contact]
    assert history.contacts == [contact]
    assert history.predictions == [prediction]
    assert history.predictions[0].request_json["power_watts"] == 55
    assert history.predictions[0].service_version == "2.4.1"
    assert history.predictions[0].response_json["raw"] == "retained"


def test_voacap_correlator_skips_ineligible_qso_without_fake_prediction() -> None:
    contact = _contact(tx_power_watts=None)
    history = HistoryFake()

    result = VoacapCompletedQsoCorrelator(history, ClientFake(None)).correlate(contact)

    assert result is VoacapCorrelationDisposition.SKIPPED
    assert history.contacts == [contact]
    assert history.predictions == []


def test_enqueue_normalizes_queue_time_to_utc_and_rejects_naive_time(
    tmp_path: Path,
) -> None:
    repository = CompletedQsoIngestionRepository(tmp_path / "ingestion.sqlite3")
    local_time = datetime(2026, 10, 7, 8, 0, tzinfo=timezone(timedelta(hours=-4)))
    repository.enqueue(_contact(), queued_at_utc=local_time)
    snapshot = repository.read(CONTACT_ID)

    assert snapshot is not None and snapshot.queued_at_utc == NOW
    with pytest.raises(ValueError, match="timezone-aware"):
        repository.enqueue(
            _contact(contact_id=uuid4()),
            queued_at_utc=datetime(2026, 10, 7, 12, 0),  # noqa: DTZ001 - invalid fixture
        )


class SelectiveCorrelator:
    def __init__(self, fail_once_id: UUID) -> None:
        self._fail_once_id = fail_once_id
        self.calls: list[UUID] = []

    def correlate(self, contact: Contact) -> VoacapCorrelationDisposition:
        self.calls.append(contact.contact_id)
        if contact.contact_id == self._fail_once_id and self.calls.count(contact.contact_id) == 1:
            raise OSError("temporary VOACAP failure")
        return VoacapCorrelationDisposition.STORED


class AlwaysFailingCorrelator:
    def correlate(self, contact: Contact) -> VoacapCorrelationDisposition:
        del contact
        raise OSError("VOACAP unavailable")


class HistoryFake:
    def __init__(self) -> None:
        self.contacts: list[Contact] = []
        self.predictions: list[VoacapPrediction] = []

    def add_qso(self, contact: Contact) -> None:
        self.contacts.append(contact)

    def save_voacap(self, prediction: VoacapPrediction) -> None:
        self.predictions.append(prediction)


class ClientFake:
    def __init__(self, prediction: VoacapPrediction | None) -> None:
        self._prediction = prediction
        self.contacts: list[Contact] = []

    def predict(self, contact: Contact) -> VoacapPrediction | None:
        self.contacts.append(contact)
        return self._prediction


def _contact(
    *,
    contact_id: UUID = CONTACT_ID,
    callsign: str = "KC1OXG",
    tx_power_watts: int | None = 55,
) -> Contact:
    return Contact(
        contact_id=contact_id,
        callsign=callsign,
        frequency_hz=14_074_000,
        mode=RadioMode.FT8,
        started_at=datetime(2026, 10, 7, 7, 2, 3, tzinfo=timezone(timedelta(hours=-4))),
        rst_sent="-10",
        rst_received="-12",
        grid="FN31pr",
        contact_latitude=41.2,
        contact_longitude=-72.7,
        my_grid="EM79xp",
        my_latitude=39.1,
        my_longitude=-84.5,
        my_state="OH",
        my_cq_zone=4,
        my_itu_zone=8,
        source=ContactSource.FT8,
        tx_power_watts=tx_power_watts,
    )
