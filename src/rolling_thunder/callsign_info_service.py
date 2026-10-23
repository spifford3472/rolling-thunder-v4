"""Background Pi callsign-info lifecycle with stale-response invalidation."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from dataclasses import dataclass
from threading import Lock
from time import monotonic
from typing import Protocol

from rolling_thunder.callsign_info import CallsignInfoFailure, CallsignInfoResponse
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
    target_latitude: float | None = None
    target_longitude: float | None = None
    failure: CallsignInfoFailure | None = None
    presentation_active: bool = False
    presentation_suppressed: bool = False


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
        self._observed_at: float | None = None
        self._presentation_active = False
        self._presentation_suppressed = False
        self._last_error: str | None = None
        self._failure: CallsignInfoFailure | None = None
        self._target_latitude: float | None = None
        self._target_longitude: float | None = None
        self._future: Future[None] | None = None
        self._stopped = False

    @property
    def state(self) -> CallsignInfoState:
        now = self._clock()
        with self._lock:
            response_expired = (
                self._response is not None
                and self._shown_at is not None
                and now - self._shown_at >= self._overlay_timeout_s
            )
            pending_expired = (
                self._response is None
                and self._observed_at is not None
                and now - self._observed_at >= self._overlay_timeout_s
            )
            if self._presentation_active and (response_expired or pending_expired):
                self._generation += 1
                future = self._future
                self._future = None
                if future is not None:
                    future.cancel()
                self._response = None
                self._shown_at = None
                self._loading = False
                self._last_error = None
                self._failure = None
                self._presentation_active = False
            return CallsignInfoState(
                generation=self._generation,
                enabled=self._enabled,
                callsign=self._callsign,
                loading=self._loading,
                response=self._response,
                shown_at_monotonic=self._shown_at,
                last_error=self._last_error,
                failure=self._failure,
                target_latitude=self._target_latitude,
                target_longitude=self._target_longitude,
                presentation_active=self._presentation_active,
                presentation_suppressed=self._presentation_suppressed,
            )

    def set_enabled(self, enabled: bool) -> bool:
        with self._lock:
            if self._enabled == enabled:
                return False
            self._enabled = enabled
            if enabled:
                self._presentation_suppressed = False
            self._invalidate_locked(clear_callsign=not enabled)
            return True

    def dismiss_presentation(self) -> bool:
        """Hide the popup until a later explicit station-selection rearm."""
        with self._lock:
            if self._stopped:
                return False
            changed = not self._presentation_suppressed or any(
                (
                    self._callsign is not None,
                    self._loading,
                    self._response is not None,
                    self._presentation_active,
                )
            )
            if not changed:
                return False
            self._presentation_suppressed = True
            self._invalidate_locked(clear_callsign=True)
            return True

    def rearm_presentation(self) -> bool:
        """Allow one fresh popup lifecycle after explicit station selection."""
        with self._lock:
            if self._stopped:
                return False
            self._presentation_suppressed = False
            # Explicit selection is also the intentional retry boundary for the
            # same station after navigation dismissal, timeout, or lookup failure.
            self._invalidate_locked(clear_callsign=True)
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
            if self._presentation_suppressed:
                return False
            if not normalized:
                if self._callsign is not None or self._response is not None or self._loading:
                    self._invalidate_locked(clear_callsign=True)
                return False
            # One pending callsign gets at most one lookup/presentation lifecycle.
            # Failure or timeout stays quiet until the callsign changes or is cleared.
            if self._callsign == normalized:
                return False

            self._generation += 1
            generation = self._generation
            self._callsign = normalized
            self._loading = True
            self._response = None
            self._shown_at = None
            self._observed_at = self._clock()
            self._presentation_active = True
            self._last_error = None
            self._failure = None
            self._target_latitude = pota_latitude
            self._target_longitude = pota_longitude
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
            failure = (
                error.failure
                if isinstance(error, CallsignInfoClientError)
                else CallsignInfoFailure.SERVICE_UNAVAILABLE
            )
            with self._lock:
                if generation != self._generation or callsign != self._callsign:
                    return
                self._loading = False
                self._response = None
                self._shown_at = None
                self._last_error = failure.value
                self._failure = failure
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
            self._failure = None

    def _invalidate_locked(self, *, clear_callsign: bool) -> None:
        self._generation += 1
        future = self._future
        self._future = None
        if future is not None:
            future.cancel()
        self._loading = False
        self._response = None
        self._shown_at = None
        self._observed_at = None
        self._presentation_active = False
        self._last_error = None
        self._failure = None
        if clear_callsign:
            self._callsign = None
            self._target_latitude = None
            self._target_longitude = None
