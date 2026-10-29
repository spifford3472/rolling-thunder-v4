"""Inert controller health policy; no transport, event, or radio authority."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum


class TransportHealthState(StrEnum):
    """Lifecycle states for a future single-owner USB adapter."""

    STOPPED = "stopped"
    BACKOFF = "backoff"
    SYNCHRONIZING = "synchronizing"
    HEALTHY = "healthy"
    STALE = "stale"


@dataclass(frozen=True)
class TransportHealthSnapshot:
    """Immutable diagnostic data, never permission to dispatch an action."""

    state: TransportHealthState
    generation: int | None
    next_retry_at: float | None
    last_valid_health_at: float | None
    attempt_count: int
    last_error: str | None


class ControlTransportHealthPolicy:
    """Pure single-owner policy driven only by explicit host monotonic times.

    The explicit serial_v2 worker composes this policy. RTCTRL/1 cannot validate a fresh
    session; a future adapter must establish that separately before calling
    validated_session. An open serial fd is insufficient.
    """

    _DELAYS = (0.5, 1.0, 2.0, 4.0, 8.0)

    def __init__(self, *, stale_after_s: float = 3.0, stable_after_s: float = 10.0) -> None:
        for value in (stale_after_s, stable_after_s):
            if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
                raise ValueError("Health intervals must be finite and positive.")
        self._stale_after = stale_after_s
        self._stable_after = stable_after_s
        self._state = TransportHealthState.STOPPED
        self._generation: int | None = None
        self._serial = 0
        self._retry_at: float | None = None
        self._last_health: float | None = None
        self._healthy_since: float | None = None
        self._attempt_started: float | None = None
        self._last_time: float | None = None
        self._attempt_count = 0
        self._backoff = 0
        self._error: str | None = None

    @property
    def snapshot(self) -> TransportHealthSnapshot:
        """Return a detached immutable view without advancing time."""
        return TransportHealthSnapshot(
            self._state, self._generation, self._retry_at,
            self._last_health, self._attempt_count, self._error,
        )

    def start(self, now: float) -> None:
        """Schedule the initial attempt; repeated start never rearms a session."""
        self._time(now)
        if self._state is TransportHealthState.STOPPED:
            self._state = TransportHealthState.BACKOFF
            self._retry_at = now
            self._backoff = 0
        else:
            self._expire(now)

    def stop(self, now: float) -> None:
        """Invalidate the active generation and cancel all scheduled work."""
        self._time(now)
        self._generation = None
        self._retry_at = None
        self._healthy_since = None
        self._attempt_started = None
        self._state = TransportHealthState.STOPPED

    def advance(self, now: float) -> None:
        """Expire missed health/handshake deadlines without issuing an attempt."""
        self._time(now)
        self._expire(now)

    def attempt_if_due(self, now: float) -> int | None:
        """Issue one unique token; the adapter still owns bounded I/O work."""
        self._time(now)
        self._expire(now)
        if self._retry_at is None or now < self._retry_at:
            return None
        self._serial += 1
        self._generation = self._serial
        self._attempt_count += 1
        self._retry_at = None
        self._attempt_started = now
        self._last_health = None
        self._state = TransportHealthState.SYNCHRONIZING
        return self._generation

    def validated_session(self, generation: int, now: float) -> None:
        """Accept only a separately proven fresh session for this attempt."""
        self._time(now)
        self._expire(now)
        if self._matches(generation) and self._state is TransportHealthState.SYNCHRONIZING:
            self._last_health = now
            self._healthy_since = now
            self._state = TransportHealthState.HEALTHY

    def heartbeat(self, generation: int, now: float) -> None:
        """Refresh only live validated health; a late heartbeat cannot revive it."""
        self._time(now)
        self._expire(now)
        if self._matches(generation) and self._state is TransportHealthState.HEALTHY:
            self._last_health = now

    def failed(self, generation: int, now: float, error: str) -> None:
        """Invalidate a current attempt and schedule its bounded retry."""
        self._time(now)
        self._expire(now)
        if self._matches(generation):
            self._lose(now, error, TransportHealthState.BACKOFF)

    def _matches(self, generation: int) -> bool:
        return type(generation) is int and generation == self._generation

    def _time(self, now: float) -> None:
        if (
            isinstance(now, bool) or not math.isfinite(now) or now < 0
            or (self._last_time is not None and now < self._last_time)
        ):
            raise ValueError("Time must be finite, nonnegative and nonregressing.")
        self._last_time = now

    def _expire(self, now: float) -> None:
        if self._state is TransportHealthState.SYNCHRONIZING:
            if self._attempt_started is not None and now - self._attempt_started >= self._stale_after:
                self._lose(now, "Session validation timed out", TransportHealthState.STALE)
        elif self._state is TransportHealthState.HEALTHY:
            if self._last_health is not None and now - self._last_health >= self._stale_after:
                self._lose(now, "Controller health expired", TransportHealthState.STALE)
            elif self._healthy_since is not None and now - self._healthy_since >= self._stable_after:
                self._backoff = 0

    def _lose(self, now: float, error: str, state: TransportHealthState) -> None:
        self._error = error[:256]
        self._generation = None
        self._healthy_since = None
        self._attempt_started = None
        self._retry_at = now + self._DELAYS[self._backoff]
        self._backoff = min(self._backoff + 1, len(self._DELAYS) - 1)
        self._state = state
