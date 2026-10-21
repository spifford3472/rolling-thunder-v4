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
    _legacy_payload_sha256,
    _pre_phase_b_payload_sha256,
    _previous_payload_sha256,
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
        tx_power_start_watts=20,
        tx_power_end_watts=25,
        tx_power_max_watts=25,
        power_meter_raw=1,
        swr_meter_raw=2,
        alc_meter_raw=3,
        sent_report_db=-10,
        received_report_db=-8 if success else None,
        local_grid="EM79xm",
        local_latitude=39.25,
        local_longitude=-84.55,
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
    assert version == (4,)

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
    assert row["tx_power_start_watts"] == 20
    assert row["tx_power_end_watts"] == 25
    assert row["tx_power_max_watts"] == 25
    assert row["busy_extension_attempts"] == 0
    assert row["power_meter_raw"] == 1
    assert row["swr_meter_raw"] == 2
    assert row["alc_meter_raw"] == 3
    assert row["local_grid"] == "EM79xm"
    assert row["local_latitude"] == pytest.approx(39.25)
    assert row["local_longitude"] == pytest.approx(-84.55)
    assert row["remote_grid"] == "FN31pr"
    assert row["distance_km"] == pytest.approx(1000.0)
    assert row["voacap_probability"] is None
    assert row["voacap_predicted_snr_db"] is None
    assert row["voacap_path"] is None


def test_v1_schema_migrates_through_v4_without_losing_attempts(tmp_path: Path) -> None:
    database = tmp_path / "forge.db"
    repository = ForgeFT8PerformanceRepository(database)
    attempt = _attempt()
    repository.persist(attempt)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE forge_ft8_performance_schema SET schema_version = 1"
        )
        connection.execute(
            "ALTER TABLE ft8_performance_attempts DROP COLUMN tx_power_start_watts"
        )
        connection.execute(
            "ALTER TABLE ft8_performance_attempts DROP COLUMN tx_power_end_watts"
        )
        connection.execute(
            "ALTER TABLE ft8_performance_attempts DROP COLUMN tx_power_max_watts"
        )
        connection.execute(
            "ALTER TABLE ft8_performance_attempts DROP COLUMN busy_extension_attempts"
        )
        connection.execute(
            "ALTER TABLE ft8_performance_attempts DROP COLUMN local_latitude"
        )
        connection.execute(
            "ALTER TABLE ft8_performance_attempts DROP COLUMN local_longitude"
        )
        connection.execute(
            "UPDATE ft8_performance_attempts SET payload_sha256=? WHERE attempt_id=?",
            (_legacy_payload_sha256(attempt), str(attempt.attempt_id)),
        )
        connection.commit()

    migrated = ForgeFT8PerformanceRepository(database)
    row = migrated.get_row(str(attempt.attempt_id))

    assert row is not None
    assert row["callsign"] == "K1ABC"
    assert row["tx_power_start_watts"] is None
    assert row["tx_power_end_watts"] is None
    assert row["tx_power_max_watts"] is None
    assert row["busy_extension_attempts"] == 0
    assert row["local_latitude"] is None
    assert row["local_longitude"] is None
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT schema_version FROM forge_ft8_performance_schema"
        ).fetchone() == (4,)
    assert migrated.persist(attempt) is FT8PerformanceUploadDisposition.ALREADY_EXISTS
    with pytest.raises(ForgeFT8PerformanceConflictError):
        migrated.persist(attempt.model_copy(update={"callsign": "W9XYZ"}))


def test_preparation_failure_persists_with_unknown_radio_context(
    tmp_path: Path,
) -> None:
    repository = ForgeFT8PerformanceRepository(tmp_path / "forge.db")
    started = datetime(2026, 10, 2, 20, 0, tzinfo=UTC)
    attempt = FT8PerformanceAttempt(
        attempt_id=UUID("00000000-0000-0000-0000-000000000399"),
        callsign="K1ABC",
        outcome=FT8AttemptOutcome.PREPARATION_FAILED,
        success=False,
        terminal_state="preparation_failed",
        terminal_reason="radio frequency unavailable",
        started_at_utc=started,
        ended_at_utc=started + timedelta(seconds=1),
        utc_date=date(2026, 10, 2),
        band=None,
        dial_frequency_hz=None,
        sent_report_db=-8,
        local_grid="EM79xm",
        remote_grid="FN31",
        audio_frequency_hz=1500,
    )

    assert repository.persist(attempt) is FT8PerformanceUploadDisposition.ACCEPTED

    row = repository.get_row(str(attempt.attempt_id))
    assert row is not None
    assert row["band"] is None
    assert row["dial_frequency_hz"] is None


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

    with pytest.raises(ForgeFT8PerformanceConflictError):
        repository.persist(attempt.model_copy(update={"local_latitude": 39.26}))


def test_service_returns_typed_utc_acknowledgement(tmp_path: Path) -> None:
    now = datetime(2026, 10, 2, 20, 5, tzinfo=UTC)
    service = ForgeFT8PerformanceService(
        ForgeFT8PerformanceRepository(tmp_path / "forge.db"),
        clock=lambda: now,
    )

    result = service.persist(_attempt())

    assert result.disposition is FT8PerformanceUploadDisposition.ACCEPTED
    assert result.received_at_utc == now


def test_cp31_busy_extension_persists_and_v2_migration_preserves_history(
    tmp_path: Path,
) -> None:
    database = tmp_path / "forge.db"
    repository = ForgeFT8PerformanceRepository(database)
    old_attempt = _attempt()
    repository.persist(old_attempt)
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE forge_ft8_performance_schema SET schema_version = 2")
        connection.execute(
            "ALTER TABLE ft8_performance_attempts DROP COLUMN busy_extension_attempts"
        )
        connection.execute(
            "ALTER TABLE ft8_performance_attempts DROP COLUMN local_latitude"
        )
        connection.execute(
            "ALTER TABLE ft8_performance_attempts DROP COLUMN local_longitude"
        )
        connection.execute(
            "UPDATE ft8_performance_attempts SET payload_sha256=? WHERE attempt_id=?",
            (_previous_payload_sha256(old_attempt), str(old_attempt.attempt_id)),
        )
        connection.commit()

    repository = ForgeFT8PerformanceRepository(database)
    row = repository.get_row(str(old_attempt.attempt_id))
    assert row is not None
    assert row["busy_extension_attempts"] == 0
    assert row["local_latitude"] is None
    assert row["local_longitude"] is None
    assert repository.persist(old_attempt) is FT8PerformanceUploadDisposition.ALREADY_EXISTS
    new_attempt = old_attempt.model_copy(
        update={
            "attempt_id": UUID("00000000-0000-0000-0000-000000009999"),
            "busy_extension_attempts": 2,
        }
    )
    assert repository.persist(new_attempt) is FT8PerformanceUploadDisposition.ACCEPTED
    new_row = repository.get_row(str(new_attempt.attempt_id))
    assert new_row is not None
    assert new_row["busy_extension_attempts"] == 2


def test_v3_schema_adds_coordinates_and_preserves_186_legacy_rows_and_hash_replay(
    tmp_path: Path,
) -> None:
    database = tmp_path / "forge.db"
    repository = ForgeFT8PerformanceRepository(database)
    attempts = [
        _attempt(
            attempt_id=UUID(f"00000000-0000-0000-0000-{index:012d}"),
        )
        for index in range(1, 187)
    ]
    for attempt in attempts:
        repository.persist(attempt)

    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE forge_ft8_performance_schema SET schema_version = 3"
        )
        connection.execute(
            "ALTER TABLE ft8_performance_attempts DROP COLUMN local_latitude"
        )
        connection.execute(
            "ALTER TABLE ft8_performance_attempts DROP COLUMN local_longitude"
        )
        for attempt in attempts:
            connection.execute(
                "UPDATE ft8_performance_attempts SET payload_sha256=? WHERE attempt_id=?",
                (_pre_phase_b_payload_sha256(attempt), str(attempt.attempt_id)),
            )
        connection.commit()

    migrated = ForgeFT8PerformanceRepository(database)
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT schema_version FROM forge_ft8_performance_schema"
        ).fetchone() == (4,)
        assert connection.execute(
            "SELECT COUNT(*) FROM ft8_performance_attempts"
        ).fetchone() == (186,)
        assert connection.execute(
            "SELECT COUNT(*) FROM ft8_performance_attempts "
            "WHERE local_latitude IS NULL AND local_longitude IS NULL"
        ).fetchone() == (186,)
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)

    assert (
        migrated.persist(attempts[0])
        is FT8PerformanceUploadDisposition.ALREADY_EXISTS
    )
    with pytest.raises(ForgeFT8PerformanceConflictError):
        migrated.persist(attempts[0].model_copy(update={"callsign": "W9XYZ"}))
