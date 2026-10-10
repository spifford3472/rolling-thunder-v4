"""Offline production-composition tests for the Forge PSK Reporter worker."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from json import loads
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from rolling_thunder.domain import Contact, ContactSource, RadioMode
from rolling_thunder.forge_pskreporter import PskReporterConfig
from rolling_thunder.forge_pskreporter_orchestration import (
    CompletedFt8EventDisposition,
    CompletedFt8QsoEvent,
    PskReporterCompletedEventAdapter,
    PskReporterOrchestrationHealth,
    PskReporterOrchestrationRepository,
    PskReporterWorkerDisposition,
    PskReporterWorkerResult,
)
from rolling_thunder.forge_pskreporter_worker import (
    ForgePskReporterApiApplication,
    ForgePskReporterWorkerRuntime,
    ForgePskReporterWorkerSnapshot,
    JsonFilePskReporterWorkerStatusPublisher,
)
from rolling_thunder.forge_pskreporter_worker_config import (
    ForgePskReporterWorkerConfig,
    ForgePskReporterWorkerConfigurationError,
    load_forge_pskreporter_worker_config,
)
from rolling_thunder.forge_pskreporter_worker_main import main
from rolling_thunder.ft8.performance import FT8AttemptOutcome, FT8PerformanceAttempt

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "config/forge-pskreporter-worker.example.yaml"
PRODUCTION = ROOT / "config/forge-pskreporter-worker.production.example.yaml"
NOW = datetime(2026, 10, 8, 18, 0, tzinfo=UTC)
TOKEN = "test-only-token-with-at-least-32-characters"


def test_configuration_defaults_examples_and_cadence_are_safe() -> None:
    defaults = ForgePskReporterWorkerConfig()
    example = load_forge_pskreporter_worker_config(EXAMPLE)
    production = load_forge_pskreporter_worker_config(PRODUCTION)

    for config in (defaults, example, production):
        assert config.enabled is False
        assert config.ingestion_enabled is False
        assert config.pskreporter.enabled is False
        assert config.pskreporter.minimum_query_interval_s >= 300
        assert config.pskreporter.minimum_query_interval_s == 600
        assert config.pskreporter.report_latency_s >= 300
        assert config.orchestration_database_path != config.history_database_path
        assert config.status_path not in {
            config.orchestration_database_path,
            config.history_database_path,
        }


def test_configuration_rejects_subfive_minute_cadence_and_shared_storage(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "worker.yaml"
    config_path.write_text(
        "orchestration_database_path: shared.db\n"
        "history_database_path: shared.db\n"
        "pskreporter:\n"
        "  minimum_query_interval_s: 299\n"
        "  report_latency_s: 299\n",
        encoding="utf-8",
    )

    with pytest.raises(ForgePskReporterWorkerConfigurationError, match="greater than or equal"):
        load_forge_pskreporter_worker_config(config_path)


def test_disabled_main_and_check_config_do_not_create_storage_or_require_secret(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = tmp_path / "worker.yaml"
    config_path.write_text(
        "enabled: false\n"
        "ingestion_enabled: true\n"
        "orchestration_database_path: orchestration.db\n"
        "history_database_path: history.db\n"
        "status_path: status.json\n"
        "pskreporter:\n"
        "  enabled: true\n",
        encoding="utf-8",
    )

    assert main(("--config", str(config_path), "--check-config")) == 0
    plan = loads(capsys.readouterr().out)
    assert plan["enabled"] is False
    assert plan["ingestion_enabled"] is True
    assert plan["provider_enabled"] is True
    assert main(("--config", str(config_path))) == 0
    assert "disabled" in capsys.readouterr().out
    assert not (tmp_path / "orchestration.db").exists()
    assert not (tmp_path / "history.db").exists()
    assert not (tmp_path / "status.json").exists()


def test_api_authenticates_before_parsing_and_durably_accepts_exact_replay(
    tmp_path: Path,
) -> None:
    repository = PskReporterOrchestrationRepository(tmp_path / "orchestration.db")
    sink = PskReporterCompletedEventAdapter(repository, PskReporterConfig(enabled=False))
    event = _event()
    application = ForgePskReporterApiApplication(
        sink,
        lambda: _snapshot(repository),
        ingestion_enabled=True,
        bearer_token=TOKEN,
        clock=lambda: NOW,
    )
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
        "Idempotency-Key": str(event.contact.contact_id),
    }

    unauthorized = application.handle(
        "POST",
        "/api/v1/completed-ft8-events",
        headers={"Content-Type": "application/json"},
        body=b"not-json",
    )
    accepted = application.handle(
        "POST", "/api/v1/completed-ft8-events", headers=headers, body=event.model_dump_json().encode()
    )
    replayed = application.handle(
        "POST", "/api/v1/completed-ft8-events", headers=headers, body=event.model_dump_json().encode()
    )

    assert unauthorized.status_code == 401
    assert accepted.status_code == 202
    assert loads(accepted.body)["disposition"] == CompletedFt8EventDisposition.ACCEPTED.value
    assert loads(replayed.body)["disposition"] == CompletedFt8EventDisposition.REPLAYED.value
    health = repository.health(
        now_utc=NOW,
        enabled=False,
        minimum_interval=timedelta(seconds=300),
    )
    assert health.pending_count == 1
    assert health.due_count == 0


def test_api_disabled_ingestion_rejects_even_valid_authenticated_event() -> None:
    sink = SinkFake()
    application = ForgePskReporterApiApplication(
        sink,
        lambda: _empty_snapshot(),
        ingestion_enabled=False,
        bearer_token=None,
        clock=lambda: NOW,
    )

    response = application.handle(
        "POST",
        "/api/v1/completed-ft8-events",
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
        body=_event().model_dump_json().encode(),
    )

    assert response.status_code == 503
    assert sink.events == []


def test_disabled_provider_runtime_publishes_status_without_provider_io(tmp_path: Path) -> None:
    repository = PskReporterOrchestrationRepository(tmp_path / "orchestration.db")
    status_path = tmp_path / "status.json"
    runtime = ForgePskReporterWorkerRuntime(
        DisabledWorkerFake(),
        repository,
        ingestion_enabled=True,
        provider_enabled=False,
        minimum_interval=timedelta(seconds=300),
        publisher=JsonFilePskReporterWorkerStatusPublisher(status_path),
        clock=lambda: NOW,
    )

    snapshot = runtime.run_once()
    stored = ForgePskReporterWorkerSnapshot.model_validate_json(
        status_path.read_text(encoding="utf-8")
    )

    assert snapshot.result is not None
    assert snapshot.result.disposition is PskReporterWorkerDisposition.DISABLED
    assert snapshot.health is not None
    assert snapshot.health.enabled is False
    assert stored == snapshot
    assert not any(path.suffix == ".tmp" for path in tmp_path.iterdir())


class DisabledWorkerFake:
    def run_once(self, *, now_utc: datetime) -> PskReporterWorkerResult:
        assert now_utc == NOW
        return PskReporterWorkerResult(disposition=PskReporterWorkerDisposition.DISABLED)


class SinkFake:
    def __init__(self) -> None:
        self.events: list[CompletedFt8QsoEvent] = []

    def enqueue(
        self, event: CompletedFt8QsoEvent, *, received_at_utc: datetime
    ) -> CompletedFt8EventDisposition:
        del received_at_utc
        self.events.append(event)
        return CompletedFt8EventDisposition.ACCEPTED


def _snapshot(repository: PskReporterOrchestrationRepository) -> ForgePskReporterWorkerSnapshot:
    return ForgePskReporterWorkerSnapshot(
        observed_at_utc=NOW,
        ingestion_enabled=True,
        provider_enabled=False,
        health=repository.health(
            now_utc=NOW,
            enabled=False,
            minimum_interval=timedelta(seconds=300),
        ),
    )


def _empty_snapshot() -> ForgePskReporterWorkerSnapshot:
    return ForgePskReporterWorkerSnapshot(
        observed_at_utc=NOW,
        ingestion_enabled=False,
        provider_enabled=False,
        health=PskReporterOrchestrationHealth(
            observed_at_utc=NOW,
            enabled=False,
            pending_count=0,
            due_count=0,
            completed_count=0,
            expired_count=0,
        ),
    )


def _event() -> CompletedFt8QsoEvent:
    contact_id = UUID("00000000-0000-4000-8000-000000000042")
    ended_at = NOW - timedelta(seconds=299)
    started_at = ended_at - timedelta(minutes=2)
    contact = Contact(
        contact_id=contact_id,
        callsign="K1TEST",
        frequency_hz=14_074_000,
        mode=RadioMode.FT8,
        started_at=started_at,
        rst_sent="-10",
        rst_received="-12",
        grid="FN31pr",
        my_grid="EM79xp",
        source=ContactSource.FT8,
    )
    values: dict[str, Any] = {
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
        terminal_attempt=FT8PerformanceAttempt.model_validate(values),
    )
