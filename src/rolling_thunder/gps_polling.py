"""Deterministic polling service for refreshing and reconnecting GPS state."""

from collections.abc import Callable
from datetime import UTC, datetime

from rolling_thunder.gps import (
    GPSConnectionState,
    GPSError,
    GPSReceiver,
    GPSState,
)
from rolling_thunder.radio_polling import PollScheduler, ScheduledPoll

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class GPSPollingService:
    """Refresh or reconnect one GPS receiver without overlapping reads."""

    def __init__(
        self,
        gps: GPSReceiver,
        scheduler: PollScheduler,
        *,
        interval_s: float = 1.0,
        clock: Clock = _utc_now,
    ) -> None:
        if interval_s <= 0:
            raise ValueError("GPS polling interval must be positive.")

        self._gps = gps
        self._scheduler = scheduler
        self._interval_s = interval_s
        self._clock = clock
        self._scheduled_poll: ScheduledPoll | None = None
        self._refreshing = False
        self._latest_state = gps.get_state()

    @property
    def is_running(self) -> bool:
        """Return whether future GPS refresh callbacks are scheduled."""
        return self._scheduled_poll is not None

    @property
    def latest_state(self) -> GPSState:
        """Return the latest immutable GPS state observed by the service."""
        return self._latest_state

    def start(self) -> GPSState:
        """Start GPS polling even when the receiver is initially unavailable."""
        if self.is_running:
            raise RuntimeError("GPS polling service is already running.")

        self._latest_state = self._gps.get_state()
        if self._latest_state.connection_state is not GPSConnectionState.CONNECTED:
            self._latest_state = self._connect_or_error()

        self._scheduled_poll = self._scheduler.schedule_repeating(
            self._interval_s,
            self._poll_once,
        )
        return self._latest_state

    def stop(self) -> GPSState:
        """Stop future GPS refresh callbacks and return the latest state."""
        scheduled_poll = self._scheduled_poll
        self._scheduled_poll = None
        if scheduled_poll is not None:
            scheduled_poll.cancel()
        return self._latest_state

    def _poll_once(self) -> None:
        if not self.is_running or self._refreshing:
            return

        self._refreshing = True
        try:
            if self._latest_state.connection_state is GPSConnectionState.CONNECTED:
                self._latest_state = self._gps.refresh_state()
            else:
                self._latest_state = self._connect_or_error()
        except GPSError as error:
            self._latest_state = self._error_state(error)
        finally:
            self._refreshing = False

    def _connect_or_error(self) -> GPSState:
        try:
            return self._gps.connect()
        except GPSError as error:
            return self._error_state(error)

    def _error_state(self, error: GPSError) -> GPSState:
        return GPSState(
            connection_state=GPSConnectionState.ERROR,
            position=None,
            updated_at=self._clock(),
            last_error=str(error),
        )
