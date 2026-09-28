"""Thread-backed scheduler for non-blocking radio polling."""

from collections.abc import Callable
from threading import Event, Thread, current_thread

from rolling_thunder.radio_polling import PollCallback, ScheduledPoll


class ThreadScheduledPoll:
    """Cancelable repeating callback running outside the UI thread."""

    def __init__(self, interval_s: float, callback: PollCallback) -> None:
        self._interval_s = interval_s
        self._callback = callback
        self._cancelled = Event()
        self._thread = Thread(
            target=self._run,
            name="rolling-thunder-radio-poll",
            daemon=True,
        )
        self._thread.start()

    def cancel(self) -> None:
        """Stop future callbacks and wait briefly for normal shutdown."""
        self._cancelled.set()
        if current_thread() is not self._thread:
            self._thread.join(timeout=self._interval_s + 1.0)

    def _run(self) -> None:
        while not self._cancelled.wait(self._interval_s):
            self._callback()


class ThreadingPollScheduler:
    """Schedule repeating work on a dedicated daemon thread."""

    def schedule_repeating(
        self,
        interval_s: float,
        callback: Callable[[], None],
    ) -> ScheduledPoll:
        """Start one repeating callback and return its cancellation handle."""
        if interval_s <= 0:
            raise ValueError("Polling interval must be positive.")
        return ThreadScheduledPoll(interval_s, callback)
