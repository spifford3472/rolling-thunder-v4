from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

from rolling_thunder.ft8.attempt_ledger import (
    AttemptDeliveryState,
    FT8AttemptClassification,
    FT8AttemptDeliveryWorker,
    FT8AttemptLedgerConflict,
    FT8AttemptLedgerRepository,
    build_attempt_event,
)
from rolling_thunder.ft8.hardware_transmit import FT8TransmitPeriodTelemetry
from rolling_thunder.ft8.performance import FT8AttemptOutcome, FT8PerformanceAttempt

NOW = datetime(2026, 10, 11, 23, 59, 50, tzinfo=UTC)
ATTEMPT = UUID("11111111-2222-4333-8444-555555555555")


@pytest.mark.parametrize(
    ("outcome", "extensions", "reason", "expected"),
    [
        (FT8AttemptOutcome.COMPLETED, 0, None, FT8AttemptClassification.SUCCESS),
        (FT8AttemptOutcome.RETRY_EXHAUSTED, 0, "no reply", FT8AttemptClassification.NO_ANSWER),
        (FT8AttemptOutcome.RETRY_EXHAUSTED, 2, "target busy", FT8AttemptClassification.BUSY),
        (FT8AttemptOutcome.ABORTED, 0, "operator abort", FT8AttemptClassification.ABORT),
        (FT8AttemptOutcome.ERROR, 0, "context exit interruption", FT8AttemptClassification.INTERRUPTION),
        (FT8AttemptOutcome.PREPARATION_FAILED, 0, "CAT fault", FT8AttemptClassification.FAULT),
    ],
)
def test_build_event_classifies_every_terminal_outcome_and_preserves_utc_grid_power_reports(
    outcome: FT8AttemptOutcome,
    extensions: int,
    reason: str | None,
    expected: FT8AttemptClassification,
) -> None:
    attempt = _attempt(outcome=outcome, reason=reason, extensions=extensions)
    period = FT8TransmitPeriodTelemetry(
        qso_id=ATTEMPT,
        started_at_utc=NOW + timedelta(seconds=10),
        ended_at_utc=NOW + timedelta(seconds=22),
        configured_power_watts=35,
        power_readback_verified=True,
        frequency_hz=14_074_000,
        transmitted=True,
        transmit_audio_offset_hz=1500,
    )

    event = build_attempt_event(
        attempt,
        (period,),
        created_at_utc=NOW + timedelta(minutes=1),
        contact_is_durable=outcome is FT8AttemptOutcome.COMPLETED,
    )

    assert event.classification is expected
    assert event.started_at_utc == NOW
    assert event.ended_at_utc.date().isoformat() == "2026-10-12"
    assert (event.local_grid, event.local_latitude, event.local_longitude) == (
        "EM79xp", 39.25, -84.55
    )
    assert event.remote_grid_source == "decoded_ft8"
    assert [report.direction.value for report in event.reports] == [
        "local_report_of_remote", "remote_report_of_local"
    ]
    assert event.tx_periods[0].configured_power_watts == 35
    assert event.tx_periods[0].power_source == "cat_configured_readback"


def test_local_ledger_survives_restart_and_rejects_changed_uuid_replay(tmp_path: Path) -> None:
    path = tmp_path / "mobile.sqlite"
    event = build_attempt_event(_attempt(), (), created_at_utc=NOW)
    assert FT8AttemptLedgerRepository(path).capture(event)
    reopened = FT8AttemptLedgerRepository(path)
    assert reopened.read(ATTEMPT) == event
    assert not reopened.capture(event)
    changed = event.model_copy(update={"terminal_reason": "changed"})
    with pytest.raises(FT8AttemptLedgerConflict):
        reopened.capture(changed)


def test_store_forward_retries_offline_then_acknowledges_exact_uuid(tmp_path: Path) -> None:
    repository = FT8AttemptLedgerRepository(
        tmp_path / "mobile.sqlite", retry_base=timedelta(seconds=5)
    )
    event = build_attempt_event(_attempt(), (), created_at_utc=NOW)
    repository.capture(event)

    class Sink:
        calls = 0

        def deliver(self, _event):
            self.calls += 1
            if self.calls == 1:
                raise OSError("offline")
            return ATTEMPT

    worker = FT8AttemptDeliveryWorker(repository, Sink(), worker_id="pi-a")
    assert worker.run_once(now_utc=NOW) == (0, 1)
    assert repository.state_for(ATTEMPT) is AttemptDeliveryState.RETRY
    assert worker.run_once(now_utc=NOW + timedelta(seconds=4)) == (0, 0)
    assert worker.run_once(now_utc=NOW + timedelta(seconds=5)) == (1, 0)
    assert repository.state_for(ATTEMPT) is AttemptDeliveryState.DELIVERED


def _attempt(
    *,
    outcome: FT8AttemptOutcome = FT8AttemptOutcome.ERROR,
    reason: str | None = "fault",
    extensions: int = 0,
) -> FT8PerformanceAttempt:
    success = outcome is FT8AttemptOutcome.COMPLETED
    return FT8PerformanceAttempt(
        attempt_id=ATTEMPT,
        callsign="KC1OXG",
        outcome=outcome,
        success=success,
        terminal_state=outcome.value,
        terminal_reason=None if success else reason,
        started_at_utc=NOW,
        ended_at_utc=NOW + timedelta(seconds=20),
        utc_date=NOW.date(),
        band="20m",
        dial_frequency_hz=14_074_000,
        sent_report_db=-10,
        received_report_db=-12,
        local_grid="EM79xp",
        local_latitude=39.25,
        local_longitude=-84.55,
        remote_grid="FN31",
        busy_extension_attempts=extensions,
        attempt_count=6 + extensions,
    )


def test_v2_carries_frozen_selection_and_v1_wire_hash_is_unchanged() -> None:
    """Schema-1 events must not gain a null field or change their source hash."""
    import hashlib
    import json

    from rolling_thunder.ft8.attempt_ledger import FT8AttemptEvent

    legacy = build_attempt_event(_attempt(), (), created_at_utc=NOW)
    legacy_json = legacy.model_dump(mode="json")
    assert legacy.schema_version == 1
    assert "choice_at_utc" not in legacy_json
    expected = hashlib.sha256(
        json.dumps(legacy_json, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert legacy.payload_sha256 == expected
    assert FT8AttemptEvent.model_validate_json(
        json.dumps(legacy_json)
    ).payload_sha256 == expected

    prospective = _attempt().model_copy(
        update={"choice_at_utc": _attempt().started_at_utc}
    )
    new_event = build_attempt_event(prospective, (), created_at_utc=NOW)
    assert new_event.schema_version == 2
    assert new_event.choice_at_utc == prospective.started_at_utc
    assert new_event.model_dump(mode="json")["choice_at_utc"] is not None
    assert FT8AttemptEvent.model_validate_json(
        new_event.model_dump_json()
    ).payload_sha256 == new_event.payload_sha256
