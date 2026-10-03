"""UTC-day FT8 attempt history used only to decorate eligible CQ rows."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from enum import StrEnum
from threading import RLock

from rolling_thunder.ft8.performance import FT8AttemptOutcome, FT8PerformanceAttempt
from rolling_thunder.ft8.performance_outbox import FT8PerformanceOutboxRepository


class FT8AttemptVisualState(StrEnum):
    """Operator-visible prior-attempt state for a callsign/band."""

    FAILED = "failed"
    ABORTED = "aborted"


Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class FT8AttemptHistoryService:
    """Persisted callsign/band attempt history for the current UTC date.

    This service never decides CQ eligibility. It only decorates callsigns that
    the existing CQ activity manager already considers visible.
    """

    def __init__(
        self,
        repository: FT8PerformanceOutboxRepository,
        *,
        clock: Clock = _utc_now,
    ) -> None:
        self._repository = repository
        self._clock = clock
        self._lock = RLock()
        self._utc_date = self._today()
        self._states: dict[tuple[str, str], FT8AttemptVisualState] = {}
        self._load_date(self._utc_date)

    def state_for(
        self,
        callsign: str,
        band: str | None,
    ) -> FT8AttemptVisualState | None:
        """Return today's failed/aborted marker for one callsign/band."""
        normalized_callsign = callsign.strip().upper()
        normalized_band = None if band is None else band.strip().lower()
        if not normalized_callsign or not normalized_band:
            return None
        with self._lock:
            self._roll_date_if_needed()
            return self._states.get((normalized_callsign, normalized_band))

    def record(self, attempt: FT8PerformanceAttempt) -> None:
        """Apply one durably stored terminal attempt to today's visual history."""
        with self._lock:
            self._roll_date_if_needed()
            if attempt.utc_date != self._utc_date:
                return
            self._apply(attempt)

    def _load_date(self, utc_date: date) -> None:
        attempts = sorted(
            self._repository.list_for_utc_date(utc_date),
            key=lambda attempt: (attempt.ended_at_utc, str(attempt.attempt_id)),
        )
        for attempt in attempts:
            self._apply(attempt)

    def _apply(self, attempt: FT8PerformanceAttempt) -> None:
        if attempt.band is None:
            return
        key = (attempt.callsign.strip().upper(), attempt.band.strip().lower())
        if attempt.outcome is FT8AttemptOutcome.COMPLETED:
            self._states.pop(key, None)
        elif attempt.outcome is FT8AttemptOutcome.ABORTED:
            self._states[key] = FT8AttemptVisualState.ABORTED
        elif attempt.outcome in {
            FT8AttemptOutcome.RETRY_EXHAUSTED,
            FT8AttemptOutcome.ERROR,
            FT8AttemptOutcome.PREPARATION_FAILED,
        }:
            self._states[key] = FT8AttemptVisualState.FAILED

    def _roll_date_if_needed(self) -> None:
        today = self._today()
        if today == self._utc_date:
            return
        self._utc_date = today
        self._states.clear()
        self._load_date(today)

    def _today(self) -> date:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("FT8 attempt-history clock must be timezone-aware")
        return now.astimezone(UTC).date()
