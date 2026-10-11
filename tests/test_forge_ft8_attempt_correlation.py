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
    assert diagnostics["semantic_notes"]["missing"].endswith("never zero")


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
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("PRAGMA journal_mode").fetchone() == ("wal",)


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
