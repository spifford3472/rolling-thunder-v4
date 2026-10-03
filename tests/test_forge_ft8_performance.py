"""Tests for dedicated Forge FT8 performance persistence."""

import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

from rolling_thunder.forge_ft8_performance import (
    ForgeFT8PerformanceConflictError,
    ForgeFT8PerformanceRepository,
    ForgeFT8PerformanceService,
)
from rolling_thunder.ft8.performance import (
    FT8AttemptOutcome,
    FT8PerformanceAttempt,
    FT8PerformanceUploadDisposition,
)


_DEFAULT_ATTEMPT_ID = UUID("00000000-0000-0000-0000-000000000301")

def _attempt(
    *,
    attempt_id: UUID = _DEFAULT_ATTEMPT_ID,
    callsign: str = "K1ABC",
    outcome: FT8AttemptOutcome = FT8AttemptOutcome.ABORTED,
) -> FT8PerformanceAttempt:
    started = datetime(2026, 10, 2, 20, 0, tzinfo=UTC)
    success = outcome is FT8AttemptOutcome.COMPLETED
    return FT8PerformanceAttempt(
        attempt_id=attempt_id,
        callsign=callsign,
        outcome=outcome,
        success=success,
        terminal_state=outcome.value,
        terminal_reason=None if success else "operator abort",
        started_at_utc=started,
        ended_at_utc=started + timedelta(seconds=45),
        utc_date=date(2026, 10, 2),
        band="20m",
        dial_frequency_hz=14_074_000,
        tx_power_target_watts=20,
        power_meter_raw=1,
        swr_meter_raw=2,
        alc_meter_raw=3,
        sent_report_db=-10,
        received_report_db=-8 if success else None,
        local_grid="EM79xm",
        remote_grid="FN31pr",
        distance_km=1000.0,
        audio_frequency_hz=1500,
        pota_cq=True,
        attempt_count=2,
        last_qso_state=outcome.value,
    )

def test_forge_schema_creation_preserves_existing_database_data(tmp_path: Path) -> None:
    database = tmp_path / "forge.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE existing_data (value TEXT NOT NULL)")
        connection.execute("INSERT INTO existing_data VALUES ('preserve-me')")
        connection.commit()

    ForgeFT8PerformanceRepository(database)

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT value FROM existing_data").fetchone() == (
            "preserve-me",
        )
        version = connection.execute(
            """
            SELECT schema_version
            FROM forge_ft8_performance_schema
            WHERE singleton_id = 1
            """
        ).fetchone()
    assert version == (1,)

def test_structured_attempt_persists_all_analysis_fields(tmp_path: Path) -> None:
    repository = ForgeFT8PerformanceRepository(tmp_path / "forge.db")
    attempt = _attempt(outcome=FT8AttemptOutcome.COMPLETED)

    disposition = repository.persist(attempt)
    row = repository.get_row(str(attempt.attempt_id))

    assert disposition is FT8PerformanceUploadDisposition.ACCEPTED
    assert row is not None
    assert row["callsign"] == "K1ABC"
    assert row["outcome"] == "completed"
    assert row["success"] == 1
    assert row["dial_frequency_hz"] == 14_074_000
    assert row["tx_power_target_watts"] == 20
    assert row["power_meter_raw"] == 1
    assert row["swr_meter_raw"] == 2
    assert row["alc_meter_raw"] == 3
    assert row["local_grid"] == "EM79xm"
    assert row["remote_grid"] == "FN31pr"
    assert row["distance_km"] == pytest.approx(1000.0)
    assert row["voacap_probability"] is None
    assert row["voacap_predicted_snr_db"] is None
    assert row["voacap_path"] is None


def test_identical_replay_is_idempotent_and_changed_payload_conflicts(
    tmp_path: Path,
) -> None:
    repository = ForgeFT8PerformanceRepository(tmp_path / "forge.db")
    attempt = _attempt()

    assert repository.persist(attempt) is FT8PerformanceUploadDisposition.ACCEPTED
    assert (
        repository.persist(attempt)
        is FT8PerformanceUploadDisposition.ALREADY_EXISTS
    )

    with pytest.raises(ForgeFT8PerformanceConflictError):
        repository.persist(_attempt(callsign="K2XYZ"))

def test_service_returns_typed_utc_acknowledgement(tmp_path: Path) -> None:
    now = datetime(2026, 10, 2, 20, 5, tzinfo=UTC)
    service = ForgeFT8PerformanceService(
        ForgeFT8PerformanceRepository(tmp_path / "forge.db"),
        clock=lambda: now,
    )

    result = service.persist(_attempt())

    assert result.disposition is FT8PerformanceUploadDisposition.ACCEPTED
    assert result.received_at_utc == now
