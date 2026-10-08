"""Supervised lifecycle for independent Forge environmental collection."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from threading import Event, RLock

from rolling_thunder.forge_propagation_collectors import (
    ForgePropagationHealth,
    ForgePropagationHistoryService,
)

Clock = Callable[[], datetime]
Waiter = Callable[[float], bool]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ForgePropagationCollectionRuntime:
    """Run due checks until stopped; provider cadence remains service-owned."""

    def __init__(
        self,
        service: ForgePropagationHistoryService,
        *,
        check_interval_s: float = 60.0,
        clock: Clock = _utc_now,
        waiter: Waiter | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        if check_interval_s <= 0:
            raise ValueError("propagation scheduler check interval must be positive")
        self._service = service
        self._check_interval_s = check_interval_s
        self._clock = clock
        self._stop_event = Event()
        self._waiter = waiter or self._stop_event.wait
        self._logger = logger or logging.getLogger("rolling_thunder.forge_propagation")
        self._lock = RLock()
        self._running = False

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._running

    def get_health(self) -> ForgePropagationHealth:
        return self._service.get_health(self._clock()).model_copy(
            update={"running": self.is_running}
        )

    def run_forever(self) -> None:
        """Run due collection cycles until ``stop`` or an injected waiter ends them."""
        with self._lock:
            if self._running:
                raise RuntimeError("propagation collection runtime is already running")
            self._stop_event.clear()
            self._running = True
        try:
            while not self._stop_event.is_set():
                results = self._service.collect_due(self._clock())
                changed = {name: result for name, result in results.items() if result != "not_due"}
                if changed:
                    log = (
                        self._logger.warning
                        if any(result.startswith("failed:") for result in changed.values())
                        else self._logger.info
                    )
                    log(
                        "Propagation environmental collection: %s",
                        " ".join(
                            f"{name}={result}" for name, result in sorted(changed.items())
                        ),
                    )
                if self._waiter(self._check_interval_s):
                    break
        finally:
            with self._lock:
                self._running = False

    def stop(self) -> None:
        """Request a prompt stop after any bounded in-flight provider request."""
        self._stop_event.set()
