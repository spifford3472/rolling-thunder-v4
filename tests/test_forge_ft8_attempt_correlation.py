import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

from rolling_thunder.forge_ft8_attempt_correlation import (
    AttemptInboxConflict,
    AttemptInboxRepository,
    FT8AttemptCorrelationWorker,
    VoacapAttemptHistoryRepository,
    VoacapProviderResult,
    VoacapRelation,
    VoacapRunStatus,
    model_inputs_for_attempt,
)
from rolling_thunder.ft8.attempt_ledger import (
    FT8AttemptClassification,
    FT8AttemptEvent,
    FT8AttemptTxPeriod,
)
from rolling_thunder.ft8.performance import FT8AttemptOutcome

NOW = datetime(2026, 10, 11, 23, 59, 50, tzinfo=UTC)
ATTEMPT = UUID("11111111-2222-4333-8444-555555555555")
DOCUMENTED_SYNTHETIC_ATTEMPT = UUID("9ad2f0c2-ed0e-4ba7-8b03-732d8aa8c339")
PHASE_B_SYNTHETIC_ATTEMPT = UUID("1d99bba6-0f38-4069-a706-77f9a90d4a8c")


def test_authenticated_inbox_store_is_idempotent_and_conflicting_replay_fails(tmp_path: Path) -> None:
    inbox = AttemptInboxRepository(tmp_path / "inbox.sqlite")
    event = _event()
    assert inbox.enqueue(event, received_at_utc=NOW)
    assert not inbox.enqueue(event, received_at_utc=NOW + timedelta(seconds=1))
    with pytest.raises(AttemptInboxConflict):
        inbox.enqueue(
            event.model_copy(update={"terminal_reason": "changed"}),
            received_at_utc=NOW,
        )


def test_model_inputs_preserve_direction_utc_period_power_and_missing_reverse_power() -> None:
    forward, reverse = model_inputs_for_attempt(_event())
    assert forward.direction.value == "local_to_remote"
    assert forward.event_hour_utc == datetime(2026, 10, 11, 23, tzinfo=UTC)
    assert forward.tx_power_watts == 35
    assert forward.tx_power_source == "cat_configured_readback"
    assert forward.tx_grid_precision == 6
    assert forward.rx_grid_precision == 4
    assert forward.provider_request()["power_watts"] == 35  # type: ignore[index]
    assert reverse.direction.value == "remote_to_local"
    assert reverse.tx_power_watts is None
    assert reverse.provider_request() is None
    assert forward.input_hash != reverse.input_hash


def test_each_changed_period_power_gets_distinct_input_hash() -> None:
    event = _event()
    second = event.tx_periods[0].model_copy(
        update={"sequence": 2, "configured_power_watts": 40}
    )
    inputs = model_inputs_for_attempt(
        event.model_copy(update={"tx_periods": event.tx_periods + (second,)})
    )

    assert [item.tx_power_watts for item in inputs] == [35, 40, None]
    assert len({item.input_hash for item in inputs}) == 3


def test_worker_retries_provider_outage_then_writes_immutable_diagnostics(tmp_path: Path) -> None:
    inbox = AttemptInboxRepository(
        tmp_path / "inbox.sqlite", retry_base=timedelta(seconds=1)
    )
    history = VoacapAttemptHistoryRepository(tmp_path / "history.sqlite")
    inbox.enqueue(_event(), received_at_utc=NOW)

    class Provider:
        calls = 0

        def predict(self, _model_input):
            self.calls += 1
            if self.calls == 1:
                raise OSError("provider offline")
            return VoacapProviderResult(
                service_version="0.3.0",
                response_json={"hour": 23},
                reliability_fraction=0.71,
                snr_db_hz=42.0,
            )

    worker = FT8AttemptCorrelationWorker(
        inbox, history, Provider(), worker_id="forge-a", clock=lambda: NOW
    )
    assert worker.run_once(now_utc=NOW) == (0, 1)
    assert worker.run_once(now_utc=NOW + timedelta(seconds=1)) == (1, 0)
    diagnostics = history.diagnostics(ATTEMPT)
    assert len(diagnostics["correlations"]) == 3
    failed, ready, skipped = diagnostics["correlations"]
    assert failed["status"] == "failed"
    assert failed["failure_reason"] == "provider offline"
    assert ready["status"] == "ready"
    assert ready["reliability_fraction"] == 0.71
    assert ready["snr_db_hz"] == 42.0
    assert ready["relation"] == "retrospective"
    assert not ready["training_eligible"]
    assert skipped["status"] == "skipped"
    assert diagnostics["provenance"]["classification"] == "unknown"
    assert diagnostics["provenance"]["voacap_processing_eligible"] is True
    assert diagnostics["provenance"]["training_eligible"] is False
    assert diagnostics["semantic_notes"]["missing"].endswith("never zero")


def test_documented_synthetic_uuid_is_audited_and_excluded_without_payload_change(
    tmp_path: Path,
) -> None:
    inbox_path = tmp_path / "inbox.sqlite"
    history_path = tmp_path / "history.sqlite"
    inbox = AttemptInboxRepository(inbox_path)
    history = VoacapAttemptHistoryRepository(history_path)
    event = _event().model_copy(update={"attempt_uuid": DOCUMENTED_SYNTHETIC_ATTEMPT})
    original_payload = event.model_dump_json()
    original_hash = event.payload_sha256
    inbox.enqueue(event, received_at_utc=NOW)

    class Provider:
        calls = 0

        def predict(self, _model_input):
            self.calls += 1
            raise AssertionError("synthetic attempt must not reach VOACAP")

    provider = Provider()
    worker = FT8AttemptCorrelationWorker(
        inbox, history, provider, worker_id="forge-a", clock=lambda: NOW
    )

    assert worker.run_once(now_utc=NOW) == (1, 0)
    assert provider.calls == 0
    snapshot = inbox.snapshot(DOCUMENTED_SYNTHETIC_ATTEMPT)
    assert snapshot is not None
    assert snapshot["state"] == "completed"
    assert FT8AttemptEvent.model_validate(snapshot["event"]).model_dump_json() == original_payload
    with sqlite3.connect(inbox_path) as db:
        stored = db.execute(
            "SELECT payload_sha256,payload_json FROM ft8_attempt_inbox WHERE attempt_uuid=?",
            (str(DOCUMENTED_SYNTHETIC_ATTEMPT),),
        ).fetchone()
    assert stored == (original_hash, original_payload)
    assert not inbox.enqueue(event, received_at_utc=NOW + timedelta(seconds=1))
    with pytest.raises(AttemptInboxConflict):
        inbox.enqueue(
            event.model_copy(update={"terminal_reason": "changed synthetic payload"}),
            received_at_utc=NOW + timedelta(seconds=2),
        )

    diagnostics = history.diagnostics(DOCUMENTED_SYNTHETIC_ATTEMPT)
    assert diagnostics["correlations"] == []
    assert diagnostics["provenance"] == {
        "classification": "synthetic_test",
        "reason": "non-transmitted Forge FT8-P1 API acceptance record",
        "evidence_reference": "docs/engineering/FT8_P1_FORGE_STAGE_CUTOVER.md",
        "evidence_date": "2026-10-10",
        "voacap_processing_eligible": False,
        "training_eligible": False,
    }
    with sqlite3.connect(history_path) as db:
        assert db.execute("SELECT COUNT(*) FROM voacap_prediction_input_v1").fetchone() == (0,)
        assert db.execute("SELECT COUNT(*) FROM voacap_prediction_run_v1").fetchone() == (0,)
        assert db.execute("SELECT COUNT(*) FROM voacap_attempt_link_v1").fetchone() == (0,)


def test_phase_b_synthetic_ingestion_record_is_excluded_before_voacap(tmp_path: Path) -> None:
    inbox = AttemptInboxRepository(tmp_path / "inbox.sqlite")
    history = VoacapAttemptHistoryRepository(tmp_path / "history.sqlite")
    event = _event().model_copy(update={"attempt_uuid": PHASE_B_SYNTHETIC_ATTEMPT})
    inbox.enqueue(event, received_at_utc=NOW)

    class Provider:
        def predict(self, _model_input):
            raise AssertionError("Phase B synthetic record must not call provider")

    worker = FT8AttemptCorrelationWorker(
        inbox, history, Provider(), worker_id="forge-a", clock=lambda: NOW
    )
    assert worker.run_once(now_utc=NOW) == (1, 0)
    assert inbox.snapshot(PHASE_B_SYNTHETIC_ATTEMPT)["state"] == "completed"  # type: ignore[index]
    assert history.diagnostics(PHASE_B_SYNTHETIC_ATTEMPT)["correlations"] == []
    provenance = history.provenance(PHASE_B_SYNTHETIC_ATTEMPT)
    assert provenance["classification"] == "synthetic_test"
    assert provenance["voacap_processing_eligible"] is False
    assert provenance["training_eligible"] is False


def test_unknown_provenance_cannot_become_training_evidence_from_prechoice_timing(
    tmp_path: Path,
) -> None:
    history = VoacapAttemptHistoryRepository(tmp_path / "history.sqlite")
    model_input = model_inputs_for_attempt(_event())[0]
    history.record_run(
        model_input,
        requested_at_utc=NOW - timedelta(minutes=1),
        available_at_utc=NOW - timedelta(seconds=1),
        status=VoacapRunStatus.READY,
        relation=VoacapRelation.PRE_CHOICE,
        result=VoacapProviderResult(
            service_version="fake-v1",
            response_json={"source": "deterministic fake"},
        ),
    )

    diagnostics = history.diagnostics(ATTEMPT)
    assert diagnostics["provenance"]["classification"] == "unknown"
    assert diagnostics["correlations"][0]["relation"] == "pre_choice"
    assert diagnostics["correlations"][0]["training_eligible"] is False


def test_expired_final_lease_dead_letters_without_provider_call(tmp_path: Path) -> None:
    inbox = AttemptInboxRepository(tmp_path / "inbox.sqlite", max_attempts=1)
    inbox.enqueue(_event(), received_at_utc=NOW)
    assert inbox.claim_due(
        now_utc=NOW,
        worker_id="crashed",
        lease_duration=timedelta(seconds=1),
        limit=1,
    )
    assert inbox.claim_due(
        now_utc=NOW + timedelta(seconds=1),
        worker_id="replacement",
        lease_duration=timedelta(seconds=1),
        limit=1,
    ) == ()
    assert inbox.snapshot(ATTEMPT)["state"] == "dead_letter"  # type: ignore[index]


def test_additive_schema_preserves_legacy_tables_and_passes_integrity_checks(
    tmp_path: Path,
) -> None:
    path = tmp_path / "mixed-release.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE legacy_history(id INTEGER PRIMARY KEY, value TEXT)")
        db.execute("INSERT INTO legacy_history(value) VALUES('preserve-me')")
    AttemptInboxRepository(path)
    VoacapAttemptHistoryRepository(path)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT value FROM legacy_history").fetchall() == [
            ("preserve-me",)
        ]
        assert db.execute(
            "SELECT attempt_uuid,provenance FROM ft8_attempt_provenance_v1"
        ).fetchall() == [
            (str(DOCUMENTED_SYNTHETIC_ATTEMPT), "synthetic_test"),
            (str(PHASE_B_SYNTHETIC_ATTEMPT), "synthetic_test"),
        ]
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("PRAGMA journal_mode").fetchone() == ("wal",)

    VoacapAttemptHistoryRepository(path)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM ft8_attempt_provenance_v1").fetchone() == (2,)
        db.execute(
            "UPDATE ft8_attempt_provenance_v1 SET reason='conflicting claim' WHERE attempt_uuid=?",
            (str(DOCUMENTED_SYNTHETIC_ATTEMPT),),
        )
    with pytest.raises(RuntimeError, match="documented attempt provenance conflict"):
        VoacapAttemptHistoryRepository(path)


def _event() -> FT8AttemptEvent:
    return FT8AttemptEvent(
        attempt_uuid=ATTEMPT,
        source_event_created_utc=NOW + timedelta(minutes=2),
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
