"""Deterministic polling service for refreshing and reconnecting radio state."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from rolling_thunder.domain import RadioConnectionState, RadioState
from rolling_thunder.radio import Radio, RadioConnectionError

PollCallback = Callable[[], None]
Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ScheduledPoll(Protocol):
    """Cancellation boundary returned by an injected scheduler."""

    def cancel(self) -> None:
        """Cancel future callback delivery."""
        ...


class PollScheduler(Protocol):
    """Scheduler boundary used to avoid real sleeping in tests."""

    def schedule_repeating(
        self,
        interval_s: float,
        callback: PollCallback,
    ) -> ScheduledPoll:
        """Schedule callback delivery at a fixed interval."""
        ...


class RadioPollingService:
    """Refresh or reconnect one radio without overlapping hardware operations."""

    def __init__(
        self,
        radio: Radio,
        scheduler: PollScheduler,
        *,
        interval_s: float = 1.0,
        clock: Clock = _utc_now,
    ) -> None:
        if interval_s <= 0:
            raise ValueError("Radio polling interval must be positive.")

        self._radio = radio
        self._scheduler = scheduler
        self._interval_s = interval_s
        self._clock = clock
        self._scheduled_poll: ScheduledPoll | None = None
        self._refreshing = False
        self._latest_state = radio.get_state()

    @property
    def is_running(self) -> bool:
        """Return whether future radio refresh callbacks are scheduled."""
        return self._scheduled_poll is not None

    @property
    def latest_state(self) -> RadioState:
        """Return the latest immutable state observed by the service."""
        return self._latest_state

    def start(self) -> RadioState:
        """Start radio polling even when the radio is initially unavailable."""
        if self.is_running:
            raise RuntimeError("Radio polling service is already running.")

        self._latest_state = self._radio.get_state()
        if self._latest_state.connection_state is not RadioConnectionState.CONNECTED:
            self._latest_state = self._connect_or_error()

        self._scheduled_poll = self._scheduler.schedule_repeating(
            self._interval_s,
            self._poll_once,
        )
        return self._latest_state

    def stop(self) -> RadioState:
        """Stop future radio callbacks and return the latest state."""
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
            if self._latest_state.connection_state is RadioConnectionState.CONNECTED:
                self._latest_state = self._radio.refresh_state()
            else:
                self._latest_state = self._connect_or_error()
        except RadioConnectionError as error:
            self._latest_state = self._error_state(error)
        finally:
            self._refreshing = False

    def _connect_or_error(self) -> RadioState:
        try:
            return self._radio.connect()
        except RadioConnectionError as error:
            return self._error_state(error)

    def _error_state(self, error: RadioConnectionError) -> RadioState:
        radio_state = self._radio.get_state()
        previous_state = self._latest_state
        return RadioState(
            connection_state=RadioConnectionState.ERROR,
            frequency=radio_state.frequency or previous_state.frequency,
            mode=radio_state.mode or previous_state.mode,
            transmitting=False,
            updated_at=self._clock(),
            last_error=str(error) or error.__class__.__name__,
        )
