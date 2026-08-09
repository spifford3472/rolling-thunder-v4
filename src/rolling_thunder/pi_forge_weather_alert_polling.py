"""Background-only Pi polling for retained Forge weather alerts."""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import dataclass
from threading import RLock

from rolling_thunder.pi_forge_weather_alert_service import (
    PiForgeWeatherAlertService,
    PiForgeWeatherAlertState,
)
from rolling_thunder.pi_weather_alert_location_guard import (
    PiWeatherAlertLocationGuard,
)
from rolling_thunder.radio_polling import (
    PollScheduler,
    ScheduledPoll,
)
from rolling_thunder.weather_alert_notification_policy import (
    WeatherAlertNotificationController,
    WeatherAlertNotificationDecision,
    WeatherAlertNotificationEvaluation,
)

_LOGGER = logging.getLogger(
    "rolling_thunder.pi_forge_weather_alerts"
)

WeatherAlertExecutorFactory = Callable[[], Executor]


def _default_executor_factory() -> Executor:
    return ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix="rolling-thunder-pi-weather-alerts",
    )


@dataclass(frozen=True, slots=True)
class PiForgeWeatherAlertNotificationBatch:
    """Latest event-like claimed alert decisions for a future audio consumer."""

    sequence: int = 0
    decisions: tuple[
        WeatherAlertNotificationDecision,
        ...,
    ] = ()
    persistence_error: str | None = None


class PiForgeWeatherAlertPollingService:
    """Refresh and evaluate weather alerts entirely outside the UI thread."""

    def __init__(
        self,
        service: PiForgeWeatherAlertService,
        location_guard: PiWeatherAlertLocationGuard,
        notifications: WeatherAlertNotificationController,
        scheduler: PollScheduler,
        *,
        interval_s: float = 30.0,
        refresh_on_start: bool = False,
        executor_factory: WeatherAlertExecutorFactory | None = None,
    ) -> None:
        if interval_s <= 0:
            raise ValueError(
                "Pi Forge weather-alert polling interval "
                "must be positive."
            )

        self._service = service
        self._location_guard = location_guard
        self._notifications = notifications
        self._scheduler = scheduler
        self._interval_s = interval_s
        self._refresh_on_start = refresh_on_start
        self._executor_factory = (
            executor_factory or _default_executor_factory
        )

        self._lock = RLock()
        self._scheduled_poll: ScheduledPoll | None = None
        self._executor: Executor | None = None
        self._worker_pending = False
        self._refresh_count = 0

        self._notification_batch = (
            PiForgeWeatherAlertNotificationBatch()
        )

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._scheduled_poll is not None

    @property
    def is_refreshing(self) -> bool:
        with self._lock:
            return self._worker_pending

    @property
    def refresh_count(self) -> int:
        with self._lock:
            return self._refresh_count

    @property
    def latest_state(self) -> PiForgeWeatherAlertState:
        """Return current state with local GPS authority applied."""
        return self._location_guard.apply(
            self._service.get_state()
        )

    @property
    def latest_notification_batch(
        self,
    ) -> PiForgeWeatherAlertNotificationBatch:
        """Return latest event batch without performing I/O."""
        with self._lock:
            return self._notification_batch

    def start(self) -> PiForgeWeatherAlertState:
        """Schedule future alert refreshes without caller-thread I/O."""
        startup_state = self.latest_state

        with self._lock:
            if (
                self._scheduled_poll is not None
                or self._executor is not None
            ):
                raise RuntimeError(
                    "Pi Forge weather-alert polling service "
                    "is already running."
                )

            executor = self._executor_factory()

            try:
                scheduled_poll = (
                    self._scheduler.schedule_repeating(
                        self._interval_s,
                        self._poll_once,
                    )
                )
            except Exception:
                executor.shutdown(
                    wait=False,
                    cancel_futures=True,
                )
                raise

            self._executor = executor
            self._scheduled_poll = scheduled_poll

        if self._refresh_on_start:
            self._queue_refresh()

        return startup_state

    def stop(self) -> PiForgeWeatherAlertState:
        """Cancel future alert work and wait for bounded in-flight work."""
        with self._lock:
            scheduled_poll = self._scheduled_poll
            executor = self._executor

            self._scheduled_poll = None
            self._executor = None

        if scheduled_poll is not None:
            scheduled_poll.cancel()

        if executor is not None:
            executor.shutdown(
                wait=True,
                cancel_futures=True,
            )

        with self._lock:
            self._worker_pending = False

        return self.latest_state

    def _poll_once(self) -> None:
        self._queue_refresh()

    def _queue_refresh(self) -> None:
        with self._lock:
            executor = self._executor

            if (
                executor is None
                or self._scheduled_poll is None
                or self._worker_pending
            ):
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
            refreshed = self._service.refresh()
            effective = self._location_guard.apply(refreshed)

            evaluation = self._notifications.evaluate(
                effective
            )

            self._record_evaluation(evaluation)
        except Exception:
            _LOGGER.exception(
                "Unexpected Pi Forge weather-alert refresh "
                "failure; future attempts will continue."
            )
        finally:
            with self._lock:
                self._refresh_count += 1
                self._worker_pending = False

    def _record_evaluation(
        self,
        evaluation: WeatherAlertNotificationEvaluation,
    ) -> None:
        if (
            not evaluation.decisions
            and evaluation.persistence_error is None
        ):
            return

        with self._lock:
            self._notification_batch = (
                PiForgeWeatherAlertNotificationBatch(
                    sequence=(
                        self._notification_batch.sequence + 1
                    ),
                    decisions=evaluation.decisions,
                    persistence_error=(
                        evaluation.persistence_error
                    ),
                )
            )
