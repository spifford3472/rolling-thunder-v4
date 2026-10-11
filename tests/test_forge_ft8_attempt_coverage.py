"""Offline Phase-C retrospective VOACAP coverage and fail-closed invariants."""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

from rolling_thunder.forge_ft8_attempt_correlation import (
    AttemptInboxRepository,
    FT8AttemptCorrelationWorker,
    VoacapAttemptHistoryRepository,
    VoacapProviderResult,
    model_inputs_for_attempt,
)
from rolling_thunder.forge_ft8_attempt_coverage import (
    build_retrospective_coverage_report,
)
from rolling_thunder.ft8.attempt_ledger import (
    FT8AttemptClassification,
    FT8AttemptEvent,
    FT8AttemptTxPeriod,
)
from rolling_thunder.ft8.performance import FT8AttemptOutcome

NOW = datetime(2026, 10, 11, 23, 59, 50, tzinfo=UTC)
ATTEMPT = UUID("11111111-2222-4333-8444-555555555555")
SYNTHETIC = UUID("9ad2f0c2-ed0e-4ba7-8b03-732d8aa8c339")


class _Provider:
    def predict(self, _model_input):
        return VoacapProviderResult(
            service_version="fake-v1",
            response_json={"source": "deterministic fake"},
            reliability_fraction=0.75,
            snr_db_hz=40.0,
        )


def test_report_correlates_existing_history_without_writes_or_sensitive_fields(
    tmp_path: Path,
) -> None:
    inbox_path, history_path = _correlated_databases(tmp_path)
    before_inbox = _logical_dump(inbox_path)
    before_history = _logical_dump(history_path)

    report = build_retrospective_coverage_report(
        inbox_path,
        history_path,
        window_start_utc=NOW - timedelta(minutes=1),
        window_end_utc=NOW + timedelta(minutes=1),
        generated_at_utc=NOW + timedelta(hours=1),
        release_identifier="0123456789abcdef",
        inbox_snapshot_identifier="backup:inbox-20261011",
        history_snapshot_identifier="backup:history-20261011",
    )

    assert report.denominators == {
        "events": 2,
        "transmitted_periods": 2,
        "modeled_inputs": 2,
    }
    assert report.event_partitions["provenance"] == {
        "synthetic_test": 1,
        "unknown": 1,
    }
    assert report.event_partitions["processing_state"] == {"completed": 2}
    assert report.modeled_input_partitions["direction"] == {
        "local_to_remote": 1,
        "remote_to_local": 1,
    }
    assert report.run_partitions["status"] == {"ready": 1, "skipped": 1}
    assert report.run_partitions["training_eligible"] == {"ineligible": 2}
    assert report.reconciliation["excluded_attempts_with_model_history"] == 0
    assert report.reconciliation["expected_model_inputs"] == 2
    assert report.reconciliation["missing_model_input_rows"] == 0
    assert report.reconciliation["unexpected_model_input_rows"] == 0
    assert report.reconciliation["missing_terminal_run_inputs"] == 0
    assert report.reconciliation["reverse_unknown_power_inputs"] == 1
    assert report.reconciliation["reverse_unknown_power_skips"] == 1
    assert report.reconciliation["reverse_unknown_power_gaps"] == 0
    assert report.event_coverage["verified_power_period_present"].numerator == 2
    serialized = report.model_dump_json()
    assert "KC1OXG" not in serialized
    assert "39.25" not in serialized
    assert _logical_dump(inbox_path) == before_inbox
    assert _logical_dump(history_path) == before_history


def test_report_fails_closed_on_payload_digest_mismatch(tmp_path: Path) -> None:
    inbox_path, history_path = _correlated_databases(tmp_path)
    with sqlite3.connect(inbox_path) as db:
        db.execute(
            "UPDATE ft8_attempt_inbox SET payload_sha256='changed' WHERE attempt_uuid=?",
            (str(ATTEMPT),),
        )

    with pytest.raises(ValueError, match="payload digest mismatch"):
        _report(inbox_path, history_path)


def test_report_fails_closed_on_provider_response_digest_mismatch(tmp_path: Path) -> None:
    inbox_path, history_path = _correlated_databases(tmp_path)
    with sqlite3.connect(history_path) as db:
        db.execute(
            """UPDATE voacap_prediction_run_v1 SET response_sha256='changed'
            WHERE status='ready'"""
        )

    with pytest.raises(ValueError, match="response digest mismatch"):
        _report(inbox_path, history_path)


def test_report_fails_closed_when_history_uuid_is_absent_from_inbox(tmp_path: Path) -> None:
    inbox_path, history_path = _correlated_databases(tmp_path)
    orphan = _event(UUID("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"))
    history = VoacapAttemptHistoryRepository(history_path)
    history.record_input(model_inputs_for_attempt(orphan)[0])

    with pytest.raises(ValueError, match="absent from the inbox"):
        _report(inbox_path, history_path)


def test_report_rejects_training_eligible_retrospective_link(tmp_path: Path) -> None:
    inbox_path, history_path = _correlated_databases(tmp_path)
    with sqlite3.connect(history_path) as db:
        db.execute(
            "UPDATE voacap_attempt_link_v1 SET training_eligible=1 WHERE attempt_uuid=?",
            (str(ATTEMPT),),
        )

    with pytest.raises(ValueError, match="training-eligible VOACAP link"):
        _report(inbox_path, history_path)


def _correlated_databases(tmp_path: Path) -> tuple[Path, Path]:
    inbox_path = tmp_path / "inbox.sqlite"
    history_path = tmp_path / "history.sqlite"
    inbox = AttemptInboxRepository(inbox_path)
    history = VoacapAttemptHistoryRepository(history_path)
    inbox.enqueue(_event(ATTEMPT), received_at_utc=NOW)
    inbox.enqueue(_event(SYNTHETIC), received_at_utc=NOW)
    worker = FT8AttemptCorrelationWorker(
        inbox, history, _Provider(), worker_id="offline-test", clock=lambda: NOW
    )
    assert worker.run_once(now_utc=NOW) == (2, 0)
    return inbox_path, history_path


def _report(inbox_path: Path, history_path: Path):
    return build_retrospective_coverage_report(
        inbox_path,
        history_path,
        window_start_utc=NOW - timedelta(minutes=1),
        window_end_utc=NOW + timedelta(minutes=1),
        generated_at_utc=NOW,
        release_identifier="test-release",
        inbox_snapshot_identifier="test-inbox-snapshot",
        history_snapshot_identifier="test-history-snapshot",
    )


def _event(attempt_uuid: UUID) -> FT8AttemptEvent:
    return FT8AttemptEvent(
        attempt_uuid=attempt_uuid,
        source_event_created_utc=NOW + timedelta(seconds=40),
        started_at_utc=NOW,
        ended_at_utc=NOW + timedelta(seconds=30),
        classification=FT8AttemptClassification.NO_ANSWER,
        source_outcome=FT8AttemptOutcome.RETRY_EXHAUSTED,
        terminal_phase="retry_exhausted",
        terminal_reason="no answer",
        remote_callsign="KC1OXG",
        band="20m",
        dial_frequency_hz=14_074_000,
        local_grid="EM79xp",
        local_latitude=39.25,
        local_longitude=-84.55,
        remote_grid="FN31",
        remote_grid_source="decoded_ft8",
        tx_periods=(
            FT8AttemptTxPeriod(
                sequence=1,
                started_at_utc=NOW,
                ended_at_utc=NOW + timedelta(seconds=12),
                configured_power_watts=35,
                power_source="cat_configured_readback",
                frequency_hz=14_074_000,
                transmitted=True,
                transmit_audio_offset_hz=1500,
            ),
        ),
        transmit_attempt_count=1,
        busy_extension_attempts=0,
    )


def _logical_dump(path: Path) -> tuple[str, ...]:
    with sqlite3.connect(path) as db:
        return tuple(db.iterdump())
