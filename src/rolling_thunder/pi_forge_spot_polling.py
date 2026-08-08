"""Background-only polling lifecycle for Pi Forge shared spots."""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import Executor, ThreadPoolExecutor
from threading import RLock

from rolling_thunder.pi_forge_spot_service import PiForgeSpotService, PiForgeSpotState
from rolling_thunder.radio_polling import PollScheduler, ScheduledPoll

_LOGGER = logging.getLogger("rolling_thunder.pi_forge_spots")
ExecutorFactory = Callable[[], Executor]


def _default_executor_factory() -> Executor:
    """Create the single worker used for all Pi Forge refresh work."""
    return ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix="rolling-thunder-pi-forge",
    )


class PiForgeSpotPollingService:
    """Schedule Forge refreshes without performing I/O on the caller thread."""

    def __init__(
        self,
        service: PiForgeSpotService,
        scheduler: PollScheduler,
        *,
        interval_s: float = 60.0,
        refresh_on_start: bool = True,
        executor_factory: ExecutorFactory | None = None,
    ) -> None:
        if interval_s <= 0:
            raise ValueError("Pi Forge polling interval must be positive.")

        self._service = service
        self._scheduler = scheduler
        self._interval_s = interval_s
        self._refresh_on_start = refresh_on_start
        self._executor_factory = executor_factory or _default_executor_factory
        self._lock = RLock()
        self._scheduled_poll: ScheduledPoll | None = None
        self._executor: Executor | None = None
        self._worker_pending = False
        self._refresh_count = 0

    @property
    def is_running(self) -> bool:
        """Return whether future Forge refresh callbacks are scheduled."""
        with self._lock:
            return self._scheduled_poll is not None

    @property
    def is_refreshing(self) -> bool:
        """Return whether one worker refresh is queued or executing."""
        with self._lock:
            return self._worker_pending

    @property
    def refresh_count(self) -> int:
        """Return the number of completed worker refresh attempts."""
        with self._lock:
            return self._refresh_count

    @property
    def latest_state(self) -> PiForgeSpotState:
        """Return the latest immutable service state without external work."""
        return self._service.get_state()

    def start(self) -> PiForgeSpotState:
        """Start polling and optionally queue an immediate background refresh."""
        with self._lock:
            if self._scheduled_poll is not None or self._executor is not None:
                raise RuntimeError("Pi Forge spot polling service is already running.")

            executor = self._executor_factory()
            try:
                scheduled_poll = self._scheduler.schedule_repeating(
                    self._interval_s,
                    self._poll_once,
                )
            except Exception:
                executor.shutdown(wait=False, cancel_futures=True)
                raise

            self._executor = executor
            self._scheduled_poll = scheduled_poll

        if self._refresh_on_start:
            self._queue_refresh()
        return self._service.get_state()

    def stop(self) -> PiForgeSpotState:
        """Cancel future work and shut down the owned worker cleanly."""
        with self._lock:
            scheduled_poll = self._scheduled_poll
            executor = self._executor
            self._scheduled_poll = None
            self._executor = None

        if scheduled_poll is not None:
            scheduled_poll.cancel()
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)

        with self._lock:
            self._worker_pending = False
        return self._service.get_state()

    def _poll_once(self) -> None:
        self._queue_refresh()

    def _queue_refresh(self) -> None:
        with self._lock:
            executor = self._executor
            if executor is None or self._scheduled_poll is None or self._worker_pending:
                return
            self._worker_pending = True

        try:
            executor.submit(self._run_refresh)
        except Exception:
            with self._lock:
                self._worker_pending = False
            raise

    def _run_refresh(self) -> None:
        try:
            self._service.refresh()
        except Exception as error:  # noqa: BLE001 - keep future refreshes alive
            _LOGGER.exception(
                "Unexpected Pi Forge spot refresh failure; future attempts will continue: %s",
                error,
            )
        finally:
            with self._lock:
                self._refresh_count += 1
                self._worker_pending = False
