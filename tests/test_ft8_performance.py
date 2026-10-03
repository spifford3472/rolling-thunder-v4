"""Tests for structured FT8 machine-analysis telemetry."""

from datetime import UTC, date, datetime
from uuid import UUID

import pytest

from rolling_thunder.ft8.performance import FT8AttemptOutcome, FT8PerformanceAttempt


def _attempt(**updates: object) -> FT8PerformanceAttempt:
    values: dict[str, object] = {
        "attempt_id": UUID("00000000-0000-0000-0000-000000000101"),
        "callsign": "K1ABC",
        "outcome": FT8AttemptOutcome.COMPLETED,
        "success": True,
        "terminal_state": "completed",
        "started_at_utc": datetime(2026, 10, 2, 20, 0, tzinfo=UTC),
        "ended_at_utc": datetime(2026, 10, 2, 20, 1, tzinfo=UTC),
        "utc_date": date(2026, 10, 2),
        "band": "20m",
        "dial_frequency_hz": 14_074_000,
        "sent_report_db": -10,
        "received_report_db": -8,
        "local_grid": "EM79xm",
        "remote_grid": "FN31pr",
        "distance_km": 1000.0,
        "audio_frequency_hz": 1500,
        "attempt_count": 3,
        "last_qso_state": "completed",
    }
    values.update(updates)
    return FT8PerformanceAttempt.model_validate(values)


def test_completed_attempt_is_structured_and_voacap_fields_remain_null() -> None:
    attempt = _attempt()

    assert attempt.mode == "FT8"
    assert attempt.tx_power_target_watts == 20
    assert attempt.success is True
    assert attempt.voacap_probability is None
    assert attempt.voacap_predicted_snr_db is None
    assert attempt.voacap_path is None


def test_failed_attempt_requires_reason_and_is_not_success() -> None:
    attempt = _attempt(
        outcome=FT8AttemptOutcome.PREPARATION_FAILED,
        success=False,
        terminal_state="preparation_failed",
        terminal_reason="SSB-BFO verification failed",
        received_report_db=None,
    )

    assert attempt.success is False
    assert attempt.terminal_reason == "SSB-BFO verification failed"


def test_noncompleted_attempt_cannot_claim_success() -> None:
    with pytest.raises(ValueError, match="success"):
        _attempt(
            outcome=FT8AttemptOutcome.ABORTED,
            success=True,
            terminal_state="aborted",
            terminal_reason="operator abort",
        )


def test_failed_attempt_requires_terminal_reason() -> None:
    with pytest.raises(ValueError, match="terminal_reason"):
        _attempt(
            outcome=FT8AttemptOutcome.ERROR,
            success=False,
            terminal_state="error",
            terminal_reason=None,
        )


def test_utc_date_must_match_start_timestamp() -> None:
    with pytest.raises(ValueError, match="utc_date"):
        _attempt(utc_date=date(2026, 10, 3))


def test_end_cannot_precede_start() -> None:
    with pytest.raises(ValueError, match="ended_at_utc"):
        _attempt(ended_at_utc=datetime(2026, 10, 2, 19, 59, tzinfo=UTC))


def test_meter_fields_are_explicitly_nullable_before_rf() -> None:
    attempt = _attempt(
        outcome=FT8AttemptOutcome.PREPARATION_FAILED,
        success=False,
        terminal_state="preparation_failed",
        terminal_reason="CAT unavailable",
        power_meter_raw=None,
        swr_meter_raw=None,
        alc_meter_raw=None,
    )

    assert attempt.power_meter_raw is None
    assert attempt.swr_meter_raw is None
    assert attempt.alc_meter_raw is None
