"""Bounded GPS-assisted system-clock synchronization policy."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from rolling_thunder.gps import GPSState
from rolling_thunder.radio_polling import PollScheduler, ScheduledPoll

GPSStateProvider = Callable[[], GPSState | None]
MonotonicClock = Callable[[], float]
WallClock = Callable[[], datetime]


class ClockSetError(Exception):
    """Raised when the operating-system clock cannot be set."""


@runtime_checkable
class SystemClockSetter(Protocol):
    """Least-privilege port for writing the operating-system UTC clock."""

    def set_utc(self, value: datetime) -> None:
        """Set the operating-system clock to an aware UTC timestamp."""
        ...


class ClockSyncStatus(StrEnum):
    """Current policy state for GPS-assisted system-clock synchronization."""

    STOPPED = "stopped"
    WAITING_FOR_TRUST = "waiting_for_trust"
    WARMING_UP = "warming_up"
    WAITING_FOR_CADENCE = "waiting_for_cadence"
    RETRY_PENDING = "retry_pending"
    VERIFIED = "verified"
    SYNCHRONIZED = "synchronized"
    WINDOW_EXPIRED = "window_expired"


@dataclass(frozen=True)
class ClockSyncState:
    """Immutable observation of the clock-synchronization policy state."""

    status: ClockSyncStatus
    monotonic_s: float
    gps_utc: datetime | None = None
    offset_s: float | None = None
    clock_written: bool = False
    last_error: str | None = None

    def __post_init__(self) -> None:
        if self.monotonic_s < 0:
            raise ValueError("Clock-sync monotonic timestamp cannot be negative.")
        if self.gps_utc is not None:
            if self.gps_utc.tzinfo is None or self.gps_utc.utcoffset() is None:
                raise ValueError("Clock-sync GPS UTC must include timezone information.")
            object.__setattr__(self, "gps_utc", self.gps_utc.astimezone(UTC))
        if self.last_error is not None:
            normalized = self.last_error.strip()
            if not normalized:
                raise ValueError("Clock-sync error text cannot be blank.")
            object.__setattr__(self, "last_error", normalized)
        if self.clock_written and self.status is not ClockSyncStatus.SYNCHRONIZED:
            raise ValueError("Only a synchronized state may report a clock write.")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _normalize_utc(value: datetime, *, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must include timezone information.")
    return value.astimezone(UTC)


class ClockSynchronizationService:
    """Verify or set the Pi clock from trusted GPS UTC on a bounded cadence."""

    def __init__(
        self,
        gps_state_provider: GPSStateProvider,
        clock_setter: SystemClockSetter,
        scheduler: PollScheduler,
        *,
        monotonic_clock: MonotonicClock,
        wall_clock: WallClock = _utc_now,
        poll_interval_s: float = 1.0,
        initial_trust_s: float = 60.0,
        retry_interval_s: float = 60.0,
        retry_window_s: float = 600.0,
        success_interval_s: float = 43_200.0,
        tolerance_s: float = 2.0,
    ) -> None:
        if poll_interval_s <= 0:
            raise ValueError("Clock-sync poll interval must be positive.")
        if initial_trust_s <= 0:
            raise ValueError("Clock-sync initial trust interval must be positive.")
        if retry_interval_s <= 0:
            raise ValueError("Clock-sync retry interval must be positive.")
        if retry_window_s < retry_interval_s:
            raise ValueError("Clock-sync retry window must cover at least one retry interval.")
        if success_interval_s <= retry_window_s:
            raise ValueError("Clock-sync success interval must exceed the retry window.")
        if tolerance_s < 0:
            raise ValueError("Clock-sync tolerance cannot be negative.")

        self._gps_state_provider = gps_state_provider
        self._clock_setter = clock_setter
        self._scheduler = scheduler
        self._monotonic_clock = monotonic_clock
        self._wall_clock = wall_clock
        self._poll_interval_s = poll_interval_s
        self._initial_trust_s = initial_trust_s
        self._retry_interval_s = retry_interval_s
        self._retry_window_s = retry_window_s
        self._success_interval_s = success_interval_s
        self._tolerance_s = tolerance_s

        initial_now = self._monotonic_clock()
        if initial_now < 0:
            raise ValueError("Monotonic clock cannot return a negative timestamp.")
        self._scheduled_poll: ScheduledPoll | None = None
        self._trusted_since_s: float | None = None
        self._opportunity_started_s: float | None = None
        self._next_attempt_s: float | None = None
        self._next_opportunity_s = initial_now
        self._state = ClockSyncState(ClockSyncStatus.STOPPED, initial_now)

    @property
    def is_running(self) -> bool:
        """Return whether the synchronization policy is scheduled."""
        return self._scheduled_poll is not None

    @property
    def latest_state(self) -> ClockSyncState:
        """Return the latest immutable synchronization state."""
        return self._state

    def start(self) -> ClockSyncState:
        """Start policy evaluation without performing a clock write immediately."""
        if self.is_running:
            raise RuntimeError("Clock synchronization service is already running.")
        now = self._now()
        self._trusted_since_s = None
        self._opportunity_started_s = None
        self._next_attempt_s = None
        self._next_opportunity_s = now
        self._state = ClockSyncState(ClockSyncStatus.WAITING_FOR_TRUST, now)
        self._scheduled_poll = self._scheduler.schedule_repeating(
            self._poll_interval_s,
            self._poll_once,
        )
        return self._state

    def stop(self) -> ClockSyncState:
        """Stop future policy evaluation without touching the system clock."""
        scheduled = self._scheduled_poll
        self._scheduled_poll = None
        if scheduled is not None:
            scheduled.cancel()
        now = self._now()
        self._state = ClockSyncState(ClockSyncStatus.STOPPED, now)
        return self._state

    def _poll_once(self) -> None:
        if not self.is_running:
            return

        now = self._now()
        gps_utc = self._trusted_gps_utc()
        self._update_trust_window(now, gps_utc)

        if self._opportunity_started_s is not None:
            self._evaluate_open_opportunity(now, gps_utc)
            return

        if now < self._next_opportunity_s:
            self._state = ClockSyncState(
                ClockSyncStatus.WAITING_FOR_CADENCE,
                now,
                gps_utc=gps_utc,
            )
            return

        trusted_since = self._trusted_since_s
        if gps_utc is None or trusted_since is None:
            self._state = ClockSyncState(ClockSyncStatus.WAITING_FOR_TRUST, now)
            return

        if now - trusted_since < self._initial_trust_s:
            self._state = ClockSyncState(
                ClockSyncStatus.WARMING_UP,
                now,
                gps_utc=gps_utc,
            )
            return

        self._opportunity_started_s = now
        self._next_attempt_s = now
        self._evaluate_open_opportunity(now, gps_utc)

    def _evaluate_open_opportunity(
        self,
        now: float,
        gps_utc: datetime | None,
    ) -> None:
        started = self._opportunity_started_s
        if started is None:
            raise RuntimeError("Clock-sync opportunity state is inconsistent.")

        if now - started >= self._retry_window_s:
            self._opportunity_started_s = None
            self._next_attempt_s = None
            self._next_opportunity_s = started + self._success_interval_s
            self._state = ClockSyncState(
                ClockSyncStatus.WINDOW_EXPIRED,
                now,
                gps_utc=gps_utc,
                last_error="Clock synchronization retry window expired without success.",
            )
            return

        next_attempt = self._next_attempt_s
        if next_attempt is None:
            raise RuntimeError("Clock-sync retry state is inconsistent.")
        if now < next_attempt:
            self._state = ClockSyncState(
                ClockSyncStatus.RETRY_PENDING,
                now,
                gps_utc=gps_utc,
            )
            return

        if gps_utc is None:
            self._schedule_retry(
                now,
                "Trusted GPS UTC is unavailable for this synchronization attempt.",
            )
            return

        wall_utc = _normalize_utc(self._wall_clock(), label="System wall clock")
        offset_s = (gps_utc - wall_utc).total_seconds()

        if abs(offset_s) <= self._tolerance_s:
            self._complete_success(
                now,
                ClockSyncStatus.VERIFIED,
                gps_utc,
                offset_s,
                clock_written=False,
            )
            return

        try:
            self._clock_setter.set_utc(gps_utc)
        except ClockSetError as error:
            self._schedule_retry(now, str(error), gps_utc=gps_utc, offset_s=offset_s)
            return

        self._complete_success(
            now,
            ClockSyncStatus.SYNCHRONIZED,
            gps_utc,
            offset_s,
            clock_written=True,
        )

    def _schedule_retry(
        self,
        now: float,
        error: str,
        *,
        gps_utc: datetime | None = None,
        offset_s: float | None = None,
    ) -> None:
        self._next_attempt_s = now + self._retry_interval_s
        self._state = ClockSyncState(
            ClockSyncStatus.RETRY_PENDING,
            now,
            gps_utc=gps_utc,
            offset_s=offset_s,
            last_error=error,
        )

    def _complete_success(
        self,
        now: float,
        status: ClockSyncStatus,
        gps_utc: datetime,
        offset_s: float,
        *,
        clock_written: bool,
    ) -> None:
        self._opportunity_started_s = None
        self._next_attempt_s = None
        self._next_opportunity_s = now + self._success_interval_s
        self._state = ClockSyncState(
            status,
            now,
            gps_utc=gps_utc,
            offset_s=offset_s,
            clock_written=clock_written,
        )

    def _update_trust_window(self, now: float, gps_utc: datetime | None) -> None:
        if gps_utc is None:
            self._trusted_since_s = None
            return
        if self._trusted_since_s is None:
            self._trusted_since_s = now

    def _trusted_gps_utc(self) -> datetime | None:
        state = self._gps_state_provider()
        if state is None or not state.utc.trusted or state.utc.value is None:
            return None
        return _normalize_utc(state.utc.value, label="Trusted GPS UTC")

    def _now(self) -> float:
        now = self._monotonic_clock()
        if now < 0:
            raise ValueError("Monotonic clock cannot return a negative timestamp.")
        return now
