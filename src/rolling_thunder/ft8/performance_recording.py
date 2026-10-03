"""Convert FT8 attempt outcomes into durable machine-analysis rows."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from rolling_thunder.ft8.coordinator import FT8QsoResult
from rolling_thunder.ft8.distance import maidenhead_distance_km
from rolling_thunder.ft8.domain import FT8QsoState
from rolling_thunder.ft8.performance import (
    FT8AttemptOutcome,
    FT8AttemptSeed,
    FT8PerformanceAttempt,
)
from rolling_thunder.ft8.performance_outbox import FT8PerformanceOutboxRepository

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class FT8PerformanceRecorder:
    """Persist terminal attempt telemetry before asynchronous Forge delivery."""

    def __init__(
        self,
        repository: FT8PerformanceOutboxRepository,
        *,
        clock: Clock = _utc_now,
    ) -> None:
        self._repository = repository
        self._clock = clock

    def record_preparation_failure(
        self,
        seed: FT8AttemptSeed,
        reason: str,
    ) -> FT8PerformanceAttempt:
        """Persist a fail-closed CAT/radio-preparation attempt."""
        ended = self._timestamp()
        attempt = FT8PerformanceAttempt(
            attempt_id=seed.attempt_id,
            callsign=seed.callsign,
            outcome=FT8AttemptOutcome.PREPARATION_FAILED,
            success=False,
            terminal_state="preparation_failed",
            terminal_reason=reason,
            started_at_utc=seed.started_at_utc,
            ended_at_utc=ended,
            utc_date=seed.started_at_utc.date(),
            band=seed.band,
            dial_frequency_hz=seed.dial_frequency_hz,
            tx_power_target_watts=20,
            power_meter_raw=None,
            swr_meter_raw=None,
            alc_meter_raw=None,
            sent_report_db=seed.selected_snr_db,
            received_report_db=None,
            local_grid=seed.local_grid,
            remote_grid=seed.remote_grid,
            distance_km=_distance_km(seed.local_grid, seed.remote_grid),
            audio_frequency_hz=seed.audio_frequency_hz,
            pota_cq=seed.pota_cq,
            attempt_count=0,
            last_qso_state="preparation_failed",
        )
        return self._repository.add_idempotent(attempt)

    def record_qso_result(self, result: FT8QsoResult) -> FT8PerformanceAttempt:
        """Persist completed, aborted, exhausted, or error QSO telemetry."""
        outcome = {
            FT8QsoState.COMPLETED: FT8AttemptOutcome.COMPLETED,
            FT8QsoState.ABORTED: FT8AttemptOutcome.ABORTED,
            FT8QsoState.RETRY_EXHAUSTED: FT8AttemptOutcome.RETRY_EXHAUSTED,
            FT8QsoState.ERROR: FT8AttemptOutcome.ERROR,
        }[result.status]
        terminal_reason = result.terminal_reason
        if outcome is not FT8AttemptOutcome.COMPLETED and terminal_reason is None:
            terminal_reason = {
                FT8AttemptOutcome.ABORTED: "FT8 QSO aborted",
                FT8AttemptOutcome.RETRY_EXHAUSTED: "FT8 retry budget exhausted",
                FT8AttemptOutcome.ERROR: "FT8 QSO error",
            }[outcome]

        context = result.context
        attempt = FT8PerformanceAttempt(
            attempt_id=context.qso_id,
            callsign=context.remote_callsign,
            outcome=outcome,
            success=outcome is FT8AttemptOutcome.COMPLETED,
            terminal_state=result.status.value,
            terminal_reason=terminal_reason,
            started_at_utc=result.started_utc,
            ended_at_utc=result.ended_utc,
            utc_date=result.started_utc.astimezone(UTC).date(),
            band=context.radio_band,
            dial_frequency_hz=context.radio_frequency_hz,
            tx_power_target_watts=20,
            power_meter_raw=None,
            swr_meter_raw=None,
            alc_meter_raw=None,
            sent_report_db=result.sent_report_db,
            received_report_db=result.received_report_db,
            local_grid=context.local_grid,
            remote_grid=context.remote_grid,
            distance_km=_distance_km(context.local_grid, context.remote_grid),
            audio_frequency_hz=context.target_audio_frequency_hz,
            pota_cq=context.pota_cq,
            attempt_count=result.transmit_attempt_count,
            last_qso_state=result.status.value,
        )
        return self._repository.add_idempotent(attempt)

    def _timestamp(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("FT8 performance recorder clock must be timezone-aware")
        return value.astimezone(UTC)


def _distance_km(local_grid: str | None, remote_grid: str | None) -> float | None:
    if not local_grid or not remote_grid:
        return None
    try:
        return maidenhead_distance_km(local_grid, remote_grid)
    except ValueError:
        return None
