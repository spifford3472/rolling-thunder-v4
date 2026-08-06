"""Small daemon-thread scheduler for independent background polling services."""

import logging
from collections.abc import Callable
from threading import Event, Thread, current_thread

from rolling_thunder.radio_polling import PollCallback, PollScheduler, ScheduledPoll

_LOGGER = logging.getLogger("rolling_thunder.forge_spots")


class ThreadedScheduledPoll(ScheduledPoll):
    """One cancellable daemon-thread repeating callback."""

    def __init__(
        self,
        interval_s: float,
        callback: PollCallback,
        *,
        error_handler: Callable[[Exception], None],
    ) -> None:
        self._interval_s = interval_s
        self._callback = callback
        self._error_handler = error_handler
        self._stopped = Event()
        self._thread = Thread(
            target=self._run,
            name="rolling-thunder-forge-spot-poll",
            daemon=True,
        )
        self._thread.start()

    def cancel(self) -> None:
        """Stop future callback delivery and join from external callers."""
        self._stopped.set()
        if current_thread() is not self._thread:
            self._thread.join(timeout=max(1.0, min(self._interval_s, 5.0)))

    def _run(self) -> None:
        while not self._stopped.wait(self._interval_s):
            try:
                self._callback()
            except Exception as error:
                # Scheduled work is isolated so one unexpected callback failure
                # cannot silently terminate every future refresh attempt.
                self._error_handler(error)


class ThreadedPollScheduler(PollScheduler):
    """Production scheduler using one daemon thread per repeating poll."""

    def __init__(
        self,
        *,
        error_handler: Callable[[Exception], None] | None = None,
    ) -> None:
        self._error_handler = error_handler or self._log_callback_error

    def schedule_repeating(
        self,
        interval_s: float,
        callback: PollCallback,
    ) -> ThreadedScheduledPoll:
        """Schedule a non-immediate repeating callback."""
        if interval_s <= 0:
            raise ValueError("polling interval must be positive")
        return ThreadedScheduledPoll(
            interval_s,
            callback,
            error_handler=self._error_handler,
        )

    @staticmethod
    def _log_callback_error(error: Exception) -> None:
        _LOGGER.exception(
            "Scheduled Forge spot refresh failed; future attempts will continue: %s",
            error,
        )
