"""Offline tests for completed-FT8 PSK Reporter orchestration."""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from rolling_thunder.domain import Contact, ContactSource, RadioMode
from rolling_thunder.forge_propagation_history import (
    ForgePropagationHistoryRepository,
    PskReporterCollectionStatus,
)
from rolling_thunder.forge_pskreporter import PskReporterConfig, PskReporterHttpClient
from rolling_thunder.forge_pskreporter_orchestration import (
    CompletedFt8EventConflict,
    CompletedFt8EventDisposition,
    CompletedFt8QsoEvent,
    PskReporterCompletedEventAdapter,
    PskReporterEventState,
    PskReporterOrchestrationRepository,
    PskReporterOrchestrationWorker,
    PskReporterWindowState,
    PskReporterWorkerDisposition,
)
from rolling_thunder.ft8.performance import FT8AttemptOutcome, FT8PerformanceAttempt
from rolling_thunder.http_home_platform import UrllibHttpResponse

NOW = datetime(2026, 10, 8, 16, 0, tzinfo=UTC)


class Transport:
    def __init__(self, responses: list[UrllibHttpResponse | BaseException]) -> None:
        self.responses = responses
        self.requests: list[str] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        body: bytes | None,
        timeout_s: float,
    ) -> UrllibHttpResponse:
        del method, headers, body, timeout_s
        self.requests.append(url)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def test_event_requires_matching_successful_terminal_contract() -> None:
    event = _event(1)
    assert event.contact.contact_id == event.terminal_attempt.attempt_id

    with pytest.raises(ValueError, match="UUID"):
        CompletedFt8QsoEvent(
            contact=event.contact,
            terminal_attempt=event.terminal_attempt.model_copy(
                update={"attempt_id": UUID("00000000-0000-4000-8000-999999999999")}
            ),
        )
    with pytest.raises(ValueError, match="successful terminal"):
        CompletedFt8QsoEvent(
            contact=event.contact,
            terminal_attempt=event.terminal_attempt.model_copy(
                update={
                    "outcome": FT8AttemptOutcome.ABORTED,
                    "success": False,
                    "terminal_reason": "operator abort",
                }
            ),
        )


def test_adapter_is_exactly_idempotent_and_uses_terminal_end_plus_five_minutes(
    tmp_path: Path,
) -> None:
    database = tmp_path / "orchestration.sqlite3"
    repository = PskReporterOrchestrationRepository(database)
    adapter = PskReporterCompletedEventAdapter(
        repository, PskReporterConfig(enabled=True)
    )
    event = _event(2, ended_at=NOW - timedelta(minutes=5))

    assert (
        adapter.enqueue(event, received_at_utc=NOW - timedelta(minutes=4))
        is CompletedFt8EventDisposition.ACCEPTED
    )
    assert (
        adapter.enqueue(event, received_at_utc=NOW)
        is CompletedFt8EventDisposition.REPLAYED
    )
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT eligible_at_utc, state FROM pskreporter_completed_ft8_event"
        ).fetchone()
    assert row == ("2026-10-08T16:00:00Z", PskReporterEventState.PENDING.value)

    changed = event.model_copy(
        update={"contact": event.contact.model_copy(update={"rst_received": "-18"})}
    )
    with pytest.raises(CompletedFt8EventConflict):
        adapter.enqueue(changed, received_at_utc=NOW)


def test_worker_waits_for_exact_terminal_latency_boundary_without_provider_io(
    tmp_path: Path,
) -> None:
    orchestration, history, config, transport, worker = _worker(
        tmp_path, responses=[UrllibHttpResponse(200, b"<receptionReports/>")]
    )
    event = _event(3, ended_at=NOW - timedelta(seconds=299))
    PskReporterCompletedEventAdapter(orchestration, config).enqueue(
        event, received_at_utc=NOW - timedelta(minutes=1)
    )

    early = worker.run_once(now_utc=NOW)
    due = worker.run_once(now_utc=NOW + timedelta(seconds=1))

    assert early.disposition is PskReporterWorkerDisposition.IDLE
    assert len(transport.requests) == 1
    assert due.disposition is PskReporterWorkerDisposition.SUCCEEDED
    assert due.outcomes[0].status is PskReporterCollectionStatus.QUERIED_ZERO_REPORTS
    assert history.read_pskreporter(event.contact.contact_id) == due.outcomes[0]


def test_global_pacing_survives_restart_and_failed_query_is_not_zero(
    tmp_path: Path,
) -> None:
    database = tmp_path / "orchestration.sqlite3"
    history = ForgePropagationHistoryRepository(tmp_path / "history.sqlite3")
    config = PskReporterConfig(enabled=True)
    repository = PskReporterOrchestrationRepository(database)
    adapter = PskReporterCompletedEventAdapter(repository, config)
    first = _event(4, ended_at=NOW - timedelta(minutes=10))
    second = _event(5, ended_at=NOW - timedelta(minutes=10))
    adapter.enqueue(first, received_at_utc=NOW - timedelta(minutes=9))
    failing_transport = Transport([OSError("offline")])
    failed = PskReporterOrchestrationWorker(
        repository,
        history,
        config.model_copy(update={"maximum_qsos_per_query": 1}),
        client=PskReporterHttpClient(config, transport=failing_transport),
    ).run_once(now_utc=NOW)
    adapter.enqueue(second, received_at_utc=NOW)

    restarted_repository = PskReporterOrchestrationRepository(database)
    succeeding_transport = Transport([UrllibHttpResponse(200, b"<receptionReports/>")])
    restarted = PskReporterOrchestrationWorker(
        restarted_repository,
        history,
        config.model_copy(update={"maximum_qsos_per_query": 1}),
        client=PskReporterHttpClient(config, transport=succeeding_transport),
    )
    paced = restarted.run_once(now_utc=NOW + timedelta(seconds=299))
    due = restarted.run_once(now_utc=NOW + timedelta(seconds=300))

    assert failed.disposition is PskReporterWorkerDisposition.FAILED
    assert failed.outcomes[0].status is PskReporterCollectionStatus.QUERY_FAILED
    assert paced.disposition is PskReporterWorkerDisposition.PACED
    assert len(succeeding_transport.requests) == 1
    assert due.disposition is PskReporterWorkerDisposition.SUCCEEDED
    with sqlite3.connect(database) as connection:
        windows = connection.execute(
            "SELECT window_key, state FROM pskreporter_request_window "
            "ORDER BY reserved_at_utc"
        ).fetchall()
    assert len(windows) == 2
    assert windows[0][0] != windows[1][0]
    assert [row[1] for row in windows] == [
        PskReporterWindowState.FAILED.value,
        PskReporterWindowState.SUCCEEDED.value,
    ]


def test_batch_is_bounded_and_remaining_event_waits_for_next_global_slot(
    tmp_path: Path,
) -> None:
    orchestration, _history, config, transport, worker = _worker(
        tmp_path,
        responses=[
            UrllibHttpResponse(200, b"<receptionReports/>"),
            UrllibHttpResponse(200, b"<receptionReports/>"),
        ],
        maximum_qsos_per_query=2,
    )
    adapter = PskReporterCompletedEventAdapter(orchestration, config)
    for index in (6, 7, 8):
        adapter.enqueue(
            _event(index, ended_at=NOW - timedelta(minutes=10)),
            received_at_utc=NOW - timedelta(minutes=9),
        )

    first = worker.run_once(now_utc=NOW)
    paced = worker.run_once(now_utc=NOW + timedelta(seconds=299))
    second = worker.run_once(now_utc=NOW + timedelta(seconds=300))

    assert len(first.contact_ids) == 2
    assert paced.disposition is PskReporterWorkerDisposition.PACED
    assert len(second.contact_ids) == 1
    assert len(transport.requests) == 2
    health = orchestration.health(
        now_utc=NOW + timedelta(seconds=300),
        enabled=True,
        minimum_interval=config.minimum_query_interval,
    )
    assert health.pending_count == 0
    assert health.completed_count == 3
    assert health.last_window_state is PskReporterWindowState.SUCCEEDED


def test_restart_reconciles_durable_terminal_summary_before_reserving_provider(
    tmp_path: Path,
) -> None:
    orchestration, history, config, first_transport, first_worker = _worker(
        tmp_path, responses=[UrllibHttpResponse(200, b"<receptionReports/>")]
    )
    event = _event(9, ended_at=NOW - timedelta(minutes=10))
    PskReporterCompletedEventAdapter(orchestration, config).enqueue(
        event, received_at_utc=NOW - timedelta(minutes=9)
    )
    result = first_worker.run_once(now_utc=NOW)
    assert result.disposition is PskReporterWorkerDisposition.SUCCEEDED

    # Simulate stale inbox state left by a crash after the analytics transaction.
    with sqlite3.connect(tmp_path / "orchestration.sqlite3") as connection:
        connection.execute(
            "UPDATE pskreporter_completed_ft8_event SET state='pending' WHERE contact_id=?",
            (str(event.contact.contact_id),),
        )
    restart_transport = Transport([])
    restarted = PskReporterOrchestrationWorker(
        PskReporterOrchestrationRepository(tmp_path / "orchestration.sqlite3"),
        history,
        config,
        client=PskReporterHttpClient(config, transport=restart_transport),
    )

    idle = restarted.run_once(now_utc=NOW + timedelta(minutes=10))

    assert idle.disposition is PskReporterWorkerDisposition.IDLE
    assert len(first_transport.requests) == 1
    assert restart_transport.requests == []


def test_disabled_worker_never_reserves_or_calls_provider(tmp_path: Path) -> None:
    orchestration, history, _config, transport, _worker_instance = _worker(
        tmp_path, responses=[]
    )
    disabled = PskReporterOrchestrationWorker(
        orchestration,
        history,
        PskReporterConfig(enabled=False),
        client=PskReporterHttpClient(PskReporterConfig(enabled=False), transport=transport),
    )

    assert disabled.run_once(now_utc=NOW).disposition is PskReporterWorkerDisposition.DISABLED
    assert transport.requests == []


def _worker(
    tmp_path: Path,
    *,
    responses: list[UrllibHttpResponse | BaseException],
    maximum_qsos_per_query: int = 50,
) -> tuple[
    PskReporterOrchestrationRepository,
    ForgePropagationHistoryRepository,
    PskReporterConfig,
    Transport,
    PskReporterOrchestrationWorker,
]:
    orchestration = PskReporterOrchestrationRepository(
        tmp_path / "orchestration.sqlite3"
    )
    history = ForgePropagationHistoryRepository(tmp_path / "history.sqlite3")
    config = PskReporterConfig(
        enabled=True, maximum_qsos_per_query=maximum_qsos_per_query
    )
    transport = Transport(responses)
    worker = PskReporterOrchestrationWorker(
        orchestration,
        history,
        config,
        client=PskReporterHttpClient(config, transport=transport),
    )
    return orchestration, history, config, transport, worker


def _event(
    index: int,
    *,
    ended_at: datetime = NOW - timedelta(minutes=10),
) -> CompletedFt8QsoEvent:
    contact_id = UUID(f"00000000-0000-4000-8000-{index:012d}")
    started_at = ended_at - timedelta(minutes=2)
    contact = Contact(
        contact_id=contact_id,
        callsign=f"K{index}TEST",
        frequency_hz=14_074_000 + index,
        mode=RadioMode.FT8,
        started_at=started_at,
        rst_sent="-10",
        rst_received="-12",
        grid="FN31pr",
        my_grid="EM79xp",
        source=ContactSource.FT8,
    )
    attempt_values: dict[str, Any] = {
        "attempt_id": contact_id,
        "callsign": contact.callsign,
        "outcome": FT8AttemptOutcome.COMPLETED,
        "success": True,
        "terminal_state": "completed",
        "terminal_reason": None,
        "started_at_utc": started_at,
        "ended_at_utc": ended_at,
        "utc_date": started_at.date(),
        "band": "20m",
        "dial_frequency_hz": contact.frequency_hz,
        "sent_report_db": -10,
        "received_report_db": -12,
        "local_grid": "EM79xp",
        "remote_grid": "FN31pr",
    }
    return CompletedFt8QsoEvent(
        contact=contact,
        terminal_attempt=FT8PerformanceAttempt.model_validate(attempt_values),
    )
