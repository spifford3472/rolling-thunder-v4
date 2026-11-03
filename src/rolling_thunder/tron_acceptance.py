"""Operator-initiated live audio acceptance countdown."""

from __future__ import annotations

from math import ceil


class TronAcceptanceCountdown:
    """Require a full visible preparation period before live microphone capture."""

    def __init__(self, duration_seconds: int = 30) -> None:
        if duration_seconds < 1:
            raise ValueError("countdown must be at least one second")
        self._duration_seconds = duration_seconds
        self._deadline: float | None = None
        self._generation: int | None = None
        self._awaiting_first_display = False

    @property
    def active(self) -> bool:
        return self._awaiting_first_display or self._deadline is not None

    def start(self, generation: int) -> None:
        """Stage a countdown; its full duration starts at first Tk presentation."""
        self._deadline = None
        self._generation = generation
        self._awaiting_first_display = True

    def cancel(self) -> bool:
        """Cancel a running countdown; return whether one was active."""
        was_active = self.active
        self._deadline = None
        self._generation = None
        self._awaiting_first_display = False
        return was_active

    def remaining(self, now: float, generation: int) -> int | None:
        """Return ceil seconds, zero at readiness, or -1 after preemption."""
        if not self.active:
            return None
        if generation != self._generation:
            self.cancel()
            return -1
        if self._awaiting_first_display:
            self._deadline = now + self._duration_seconds
            self._awaiting_first_display = False
        if self._deadline is None:
            return None
        remaining = self._deadline - now
        if remaining <= 0:
            self.cancel()
            return 0
        return ceil(remaining)
