"""Deterministic background health polling for the Home Station Platform."""

from collections.abc import Callable
from datetime import UTC, datetime

from rolling_thunder.home_platform import (
    HomePlatformAvailability,
    HomePlatformClient,
    HomePlatformError,
    HomePlatformState,
)
from rolling_thunder.radio_polling import PollScheduler, ScheduledPoll

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class HomePlatformHealthService:
    """Refresh remote reachability without blocking callers or local logging."""

    def __init__(
        self,
        client: HomePlatformClient,
        scheduler: PollScheduler,
        *,
        interval_s: float = 30.0,
        clock: Clock = _utc_now,
    ) -> None:
        if interval_s <= 0:
            raise ValueError("Home platform health interval must be positive.")

        self._client = client
        self._scheduler = scheduler
        self._interval_s = interval_s
        self._clock = clock
        self._scheduled_poll: ScheduledPoll | None = None
        self._checking = False
        self._latest_state = client.get_state()

    @property
    def is_running(self) -> bool:
        """Return whether future health checks are scheduled."""
        return self._scheduled_poll is not None

    @property
    def latest_state(self) -> HomePlatformState:
        """Return the latest immutable reachability snapshot."""
        return self._latest_state

    def start(self) -> HomePlatformState:
        """Schedule health checks without performing startup network I/O."""
        if self.is_running:
            raise RuntimeError("Home platform health service is already running.")

        self._latest_state = self._client.get_state()
        self._scheduled_poll = self._scheduler.schedule_repeating(
            self._interval_s,
            self._check_once,
        )
        return self._latest_state

    def stop(self) -> HomePlatformState:
        """Stop future checks and return the latest observed state."""
        scheduled_poll = self._scheduled_poll
        self._scheduled_poll = None
        if scheduled_poll is not None:
            scheduled_poll.cancel()
        return self._latest_state

    def _check_once(self) -> None:
        if not self.is_running or self._checking:
            return

        self._checking = True
        try:
            self._latest_state = self._client.check_health()
        except HomePlatformError as error:
            self._latest_state = HomePlatformState(
                availability=HomePlatformAvailability.UNAVAILABLE,
                checked_at=self._timestamp(),
                last_error=str(error),
            )
        finally:
            self._checking = False

    def _timestamp(self) -> datetime:
        timestamp = self._clock()
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("Home platform health clock must be timezone-aware.")
        return timestamp.astimezone(UTC)
