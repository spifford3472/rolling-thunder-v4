"""Offline orchestration tests for the independent completed-QSO worker."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from rolling_thunder.domain import Contact, ContactSource, RadioMode
from rolling_thunder.forge_propagation_qso_ingestion import (
    CompletedQsoCorrelationWorker,
    CompletedQsoIngestionRepository,
    VoacapCorrelationDisposition,
)
from rolling_thunder.forge_propagation_qso_worker import (
    CompletedQsoWorkerCycleState,
    CompletedQsoWorkerOrchestrator,
    CompletedQsoWorkerSnapshot,
    JsonFileCompletedQsoWorkerStatusPublisher,
)
from rolling_thunder.forge_propagation_qso_worker_config import (
    ForgePropagationQsoWorkerConfig,
    ForgePropagationQsoWorkerConfigurationError,
    load_forge_propagation_qso_worker_config,
)
from rolling_thunder.forge_propagation_qso_worker_main import main

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "config/forge-propagation-qso-worker.example.yaml"
NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


def test_worker_configuration_and_example_are_disabled_by_default() -> None:
    defaults = ForgePropagationQsoWorkerConfig()
    example = load_forge_propagation_qso_worker_config(EXAMPLE)

    assert defaults.enabled is False
    assert defaults.voacap_enabled is False
    assert example.enabled is False
    assert example.voacap_enabled is False
    assert example.inbox_database_path != example.history_database_path
    assert example.worker_identity == "forge-propagation-qso-worker-1"


def test_worker_configuration_fails_closed_on_unsafe_bounds(tmp_path: Path) -> None:
    config_path = tmp_path / "worker.yaml"
    config_path.write_text(
        "enabled: true\n"
        "voacap_enabled: true\n"
        "inbox_database_path: same.db\n"
        "history_database_path: same.db\n"
        "lease_duration_s: 10\n"
        "provider_timeout_s: 10\n",
        encoding="utf-8",
    )

    with pytest.raises(ForgePropagationQsoWorkerConfigurationError, match="lease_duration"):
        load_forge_propagation_qso_worker_config(config_path)


def test_disabled_main_does_not_create_storage_or_contact_provider(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = tmp_path / "worker.yaml"
    config_path.write_text(
        "enabled: false\n"
        "voacap_enabled: true\n"
        "inbox_database_path: inbox.db\n"
        "history_database_path: history.db\n"
        "status_path: status.json\n",
        encoding="utf-8",
    )

    assert main(("--config", str(config_path), "--once")) == 0
    assert "disabled" in capsys.readouterr().out
    assert not (tmp_path / "inbox.db").exists()
    assert not (tmp_path / "history.db").exists()
    assert not (tmp_path / "status.json").exists()


def test_orchestrator_publishes_deterministic_identity_and_queue_state(
    tmp_path: Path,
) -> None:
    repository = CompletedQsoIngestionRepository(tmp_path / "inbox.db")
    repository.enqueue(_contact(), queued_at_utc=NOW)
    worker = CompletedQsoCorrelationWorker(
        repository,
        StoredCorrelator(),
        worker_identity="worker-test",
        batch_limit=1,
        lease_duration=timedelta(minutes=2),
    )
    publisher = PublisherFake()
    times = iter((NOW, NOW + timedelta(seconds=2)))
    orchestrator = CompletedQsoWorkerOrchestrator(
        repository,
        worker,
        worker_identity="worker-test",
        publisher=publisher,
        clock=lambda: next(times),
    )

    snapshot = orchestrator.run_once()

    assert snapshot.cycle_state is CompletedQsoWorkerCycleState.SUCCEEDED
    assert snapshot.worker_identity == "worker-test"
    assert snapshot.started_at_utc == NOW
    assert snapshot.completed_at_utc == NOW + timedelta(seconds=2)
    assert snapshot.queue.completed_count == 1
    assert snapshot.queue.due_count == 0
    assert publisher.snapshots == [snapshot]
    assert orchestrator.latest_snapshot() == snapshot


def test_orchestrator_rejects_identity_outside_published_contract(tmp_path: Path) -> None:
    repository = CompletedQsoIngestionRepository(tmp_path / "inbox.db")
    worker = CompletedQsoCorrelationWorker(
        repository,
        StoredCorrelator(),
        worker_identity="worker-valid",
    )

    with pytest.raises(ValueError, match="120 characters"):
        CompletedQsoWorkerOrchestrator(
            repository,
            worker,
            worker_identity="x" * 121,
            publisher=PublisherFake(),
        )


def test_json_status_publication_is_atomic_and_versioned(tmp_path: Path) -> None:
    repository = CompletedQsoIngestionRepository(tmp_path / "inbox.db")
    worker = CompletedQsoCorrelationWorker(
        repository,
        StoredCorrelator(),
        worker_identity="worker-idle",
    )
    status_path = tmp_path / "state" / "worker.json"
    orchestrator = CompletedQsoWorkerOrchestrator(
        repository,
        worker,
        worker_identity="worker-idle",
        publisher=JsonFileCompletedQsoWorkerStatusPublisher(status_path),
        clock=lambda: NOW,
    )

    snapshot = orchestrator.run_once()
    stored = CompletedQsoWorkerSnapshot.model_validate_json(
        status_path.read_text(encoding="utf-8")
    )

    assert stored == snapshot
    assert stored.schema_version == "1"
    assert stored.cycle_state is CompletedQsoWorkerCycleState.IDLE
    assert not any(path.suffix == ".tmp" for path in status_path.parent.iterdir())


class StoredCorrelator:
    def correlate(self, contact: Contact) -> VoacapCorrelationDisposition:
        del contact
        return VoacapCorrelationDisposition.STORED


class PublisherFake:
    def __init__(self) -> None:
        self.snapshots: list[CompletedQsoWorkerSnapshot] = []

    def publish(self, snapshot: CompletedQsoWorkerSnapshot) -> None:
        self.snapshots.append(snapshot)


def _contact() -> Contact:
    return Contact(
        callsign="KC1OXG",
        frequency_hz=14_074_000,
        mode=RadioMode.FT8,
        started_at=NOW - timedelta(minutes=1),
        rst_sent="-10",
        rst_received="-12",
        grid="FN31pr",
        my_grid="EM79xp",
        source=ContactSource.FT8,
        tx_power_watts=55,
    )
