"""Deterministic polling service for refreshing connected radio state."""

from collections.abc import Callable
from typing import Protocol

from rolling_thunder.domain import RadioConnectionState, RadioState
from rolling_thunder.radio import Radio, RadioConnectionError

PollCallback = Callable[[], None]


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
    """Refresh one connected radio without overlapping refresh operations."""

    def __init__(
        self,
        radio: Radio,
        scheduler: PollScheduler,
        *,
        interval_s: float = 1.0,
    ) -> None:
        if interval_s <= 0:
            raise ValueError("Radio polling interval must be positive.")

        self._radio = radio
        self._scheduler = scheduler
        self._interval_s = interval_s
        self._scheduled_poll: ScheduledPoll | None = None
        self._refreshing = False
        self._latest_state = radio.get_state()

    @property
    def is_running(self) -> bool:
        """Return whether future refresh callbacks are scheduled."""
        return self._scheduled_poll is not None

    @property
    def latest_state(self) -> RadioState:
        """Return the latest immutable state observed by the service."""
        return self._latest_state

    def start(self) -> RadioState:
        """Start polling a currently connected radio."""
        if self.is_running:
            raise RuntimeError("Radio polling service is already running.")

        state = self._radio.get_state()
        if state.connection_state is not RadioConnectionState.CONNECTED:
            raise RadioConnectionError(
                "Radio polling requires a connected radio."
            )

        self._latest_state = state
        self._scheduled_poll = self._scheduler.schedule_repeating(
            self._interval_s,
            self._poll_once,
        )
        return state

    def stop(self) -> RadioState:
        """Stop future refresh callbacks and return the latest state."""
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
            self._latest_state = self._radio.refresh_state()
        except RadioConnectionError:
            self._latest_state = self._radio.get_state()
            self.stop()
            return
        finally:
            self._refreshing = False

        if self._latest_state.connection_state is not RadioConnectionState.CONNECTED:
            self.stop()
