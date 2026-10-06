"""Tests for structured FT8 machine-analysis telemetry."""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

from rolling_thunder.domain import Frequency, RadioConnectionState, RadioMode, RadioState
from rolling_thunder.ft8.coordinator import FT8QsoResult
from rolling_thunder.ft8.domain import (
    FT8CQActivity,
    FT8IncomingCall,
    FT8MessageKind,
    FT8Period,
    FT8PeriodParity,
    FT8QsoContext,
    FT8QsoState,
)
from rolling_thunder.ft8.performance import FT8AttemptOutcome, FT8PerformanceAttempt
from rolling_thunder.ft8.performance_outbox import FT8PerformanceOutboxRepository
from rolling_thunder.ft8.performance_recording import (
    FT8PerformanceRecorder,
    build_ft8_attempt_seed,
    build_ft8_responder_attempt_seed,
)


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


def test_configured_power_telemetry_is_distinct_from_raw_rf_meter() -> None:
    attempt = _attempt(
        tx_power_target_watts=55,
        tx_power_start_watts=55,
        tx_power_end_watts=60,
        tx_power_max_watts=60,
        power_meter_raw=173,
    )

    assert attempt.tx_power_target_watts == 55
    assert attempt.tx_power_start_watts == 55
    assert attempt.tx_power_end_watts == 60
    assert attempt.tx_power_max_watts == 60
    assert attempt.power_meter_raw == 173


def test_attempt_seed_freezes_extreme_grid_power_before_preparation() -> None:
    started = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
    seed = build_ft8_attempt_seed(
        FT8CQActivity(
            callsign="VK2ABC",
            last_period=FT8Period.from_utc(started),
            snr_db=-10,
            dt_seconds=0.1,
            audio_frequency_hz=1500,
            grid="QF56",
        ),
        radio_state=RadioState(
            connection_state=RadioConnectionState.CONNECTED,
            frequency=Frequency(hz=14_074_000),
            mode=RadioMode.USB,
            updated_at=started,
        ),
        gps_state=None,
        home_grid="EM79xm",
        started_at_utc=started,
    )

    assert seed.local_grid == "EM79xm"
    assert seed.remote_grid == "QF56"
    assert seed.tx_power_target_watts == 70


def test_responder_seed_and_preparation_failure_preserve_initial_report(
    tmp_path: Path,
) -> None:
    started = FT8Period(100).start_utc
    seed = build_ft8_responder_attempt_seed(
        FT8IncomingCall(
            callsign="K0BQB",
            period=FT8Period(100),
            snr_db=-3,
            dt_seconds=0.1,
            audio_frequency_hz=1600,
            kind=FT8MessageKind.REPORT,
            report_db=-3,
            raw_message="KI5VNB K0BQB -03",
        ),
        radio_state=RadioState(
            connection_state=RadioConnectionState.CONNECTED,
            frequency=Frequency(hz=14_074_000),
            mode=RadioMode.USB,
            updated_at=started,
        ),
        gps_state=None,
        home_grid="EM79xm",
        started_at_utc=started,
    )
    recorder = FT8PerformanceRecorder(
        FT8PerformanceOutboxRepository(tmp_path / "contacts.db"),
        clock=lambda: started + timedelta(seconds=1),
    )

    attempt = recorder.record_preparation_failure(seed, "CAT unavailable")

    assert seed.received_report_db == -3
    assert attempt.received_report_db == -3


def test_recorder_preserves_requested_start_end_and_max_configured_power(
    tmp_path: Path,
) -> None:
    started = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
    context = FT8QsoContext(
        local_callsign="KI5VNB",
        remote_callsign="VK2ABC",
        target_audio_frequency_hz=1500,
        radio_frequency_hz=14_074_000,
        radio_band="20m",
        radio_mode="USB",
        local_grid="EM79xm",
        remote_grid="QF56",
        tx_parity=FT8PeriodParity.EVEN,
        authorized_period=FT8Period.from_utc(started),
        authorized_utc=started,
        signal_report_db=-10,
        tx_power_target_watts=70,
        tx_power_start_watts=70,
    )
    result = FT8QsoResult(
        status=FT8QsoState.ABORTED,
        context=context,
        sent_report_db=-10,
        received_report_db=None,
        started_utc=started,
        ended_utc=started + timedelta(seconds=30),
        terminal_reason="operator abort",
    )
    recorder = FT8PerformanceRecorder(
        FT8PerformanceOutboxRepository(tmp_path / "contacts.db"),
        clock=lambda: result.ended_utc,
    )

    attempt = recorder.record_qso_result(
        result,
        power_meter_raw=173,
        tx_power_end_watts=60,
    )

    assert attempt.tx_power_target_watts == 70
    assert attempt.tx_power_start_watts == 70
    assert attempt.tx_power_end_watts == 60
    assert attempt.tx_power_max_watts == 70
    assert attempt.power_meter_raw == 173
