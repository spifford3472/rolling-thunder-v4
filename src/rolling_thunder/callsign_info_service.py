"""Background Pi callsign-info lifecycle with stale-response invalidation."""

from __future__ import annotations

from concurrent.futures import Executor, Future, ThreadPoolExecutor
from dataclasses import dataclass
from threading import Lock
from time import monotonic
from typing import Callable, Protocol

from rolling_thunder.callsign_info import CallsignInfoResponse
from rolling_thunder.callsign_info_client import CallsignInfoClientError

MonotonicClock = Callable[[], float]


class CallsignInfoLookup(Protocol):
    def lookup(
        self,
        callsign: str,
        *,
        pota_latitude: float | None = None,
        pota_longitude: float | None = None,
    ) -> CallsignInfoResponse:
        ...


@dataclass(frozen=True, slots=True)
class CallsignInfoState:
    """Immutable Pi-side callsign-info presentation state."""

    generation: int
    enabled: bool
    callsign: str | None
    loading: bool
    response: CallsignInfoResponse | None
    shown_at_monotonic: float | None
    last_error: str | None = None


class CallsignInfoLookupService:
    """Own network work, generation checks, and bounded overlay lifetime."""

    def __init__(
        self,
        client: CallsignInfoLookup,
        *,
        enabled: bool = True,
        overlay_timeout_s: float = 120.0,
        executor: Executor | None = None,
        clock: MonotonicClock = monotonic,
    ) -> None:
        if not 10.0 <= overlay_timeout_s <= 120.0:
            raise ValueError("Callsign-info overlay timeout must be between 10 and 120 seconds.")
        self._client = client
        self._enabled = enabled
        self._overlay_timeout_s = overlay_timeout_s
        self._executor = executor
        self._owns_executor = executor is None
        self._clock = clock
        self._lock = Lock()
        self._generation = 0
        self._callsign: str | None = None
        self._loading = False
        self._response: CallsignInfoResponse | None = None
        self._shown_at: float | None = None
        self._last_error: str | None = None
        self._future: Future[object] | None = None
        self._stopped = False

    @property
    def state(self) -> CallsignInfoState:
        now = self._clock()
        with self._lock:
            if (
                self._response is not None
                and self._shown_at is not None
                and now - self._shown_at >= self._overlay_timeout_s
            ):
                self._generation += 1
                self._response = None
                self._shown_at = None
                self._loading = False
            return CallsignInfoState(
                generation=self._generation,
                enabled=self._enabled,
                callsign=self._callsign,
                loading=self._loading,
                response=self._response,
                shown_at_monotonic=self._shown_at,
                last_error=self._last_error,
            )

    def set_enabled(self, enabled: bool) -> bool:
        with self._lock:
            if self._enabled == enabled:
                return False
            self._enabled = enabled
            self._invalidate_locked(clear_callsign=not enabled)
            return True

    def observe_callsign(
        self,
        callsign: str | None,
        *,
        pota_latitude: float | None = None,
        pota_longitude: float | None = None,
    ) -> bool:
        normalized = callsign.strip().upper() if callsign else None
        with self._lock:
            if self._stopped:
                return False
            if not self._enabled:
                if self._callsign is not None or self._response is not None or self._loading:
                    self._invalidate_locked(clear_callsign=True)
                return False
            if not normalized:
                if self._callsign is not None or self._response is not None or self._loading:
                    self._invalidate_locked(clear_callsign=True)
                return False
            if self._callsign == normalized and (self._loading or self._response is not None):
                return False

            self._generation += 1
            generation = self._generation
            self._callsign = normalized
            self._loading = True
            self._response = None
            self._shown_at = None
            self._last_error = None
            executor = self._executor
            if executor is None:
                executor = ThreadPoolExecutor(
                    max_workers=1,
                    thread_name_prefix="rolling-thunder-callsign-info",
                )
                self._executor = executor

        future = executor.submit(
            self._lookup_worker,
            generation,
            normalized,
            pota_latitude,
            pota_longitude,
        )
        with self._lock:
            if self._generation == generation:
                self._future = future
        return True

    def clear(self) -> None:
        with self._lock:
            self._invalidate_locked(clear_callsign=True)

    def stop(self) -> None:
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            self._invalidate_locked(clear_callsign=True)
            executor = self._executor
            self._executor = None
        if executor is not None and self._owns_executor:
            executor.shutdown(wait=False, cancel_futures=True)

    def _lookup_worker(
        self,
        generation: int,
        callsign: str,
        pota_latitude: float | None,
        pota_longitude: float | None,
    ) -> None:
        try:
            response = self._client.lookup(
                callsign,
                pota_latitude=pota_latitude,
                pota_longitude=pota_longitude,
            )
        except (CallsignInfoClientError, OSError, ValueError) as error:
            with self._lock:
                if generation != self._generation or callsign != self._callsign:
                    return
                self._loading = False
                self._response = None
                self._shown_at = None
                self._last_error = str(error)
            return

        with self._lock:
            if (
                generation != self._generation
                or callsign != self._callsign
                or not self._enabled
                or self._stopped
            ):
                return
            self._loading = False
            self._response = response
            self._shown_at = self._clock()
            self._last_error = None

    def _invalidate_locked(self, *, clear_callsign: bool) -> None:
        self._generation += 1
        future = self._future
        self._future = None
        if future is not None:
            future.cancel()
        self._loading = False
        self._response = None
        self._shown_at = None
        self._last_error = None
        if clear_callsign:
            self._callsign = None
