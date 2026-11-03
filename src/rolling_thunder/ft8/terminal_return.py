"""Clock-driven FT8 terminal result hold and one-shot return policy."""

from __future__ import annotations

from rolling_thunder.ft8.domain import FT8QsoState

_TERMINAL_STATES = frozenset(
    {
        FT8QsoState.COMPLETED,
        FT8QsoState.ABORTED,
        FT8QsoState.RETRY_EXHAUSTED,
        FT8QsoState.ERROR,
    }
)


class FT8TerminalReturnTimer:
    """Return once after a visible result hold, independent of selected context."""

    def __init__(self, hold_seconds: float = 3.0) -> None:
        if hold_seconds < 0:
            raise ValueError("hold_seconds must not be negative")
        self._hold_seconds = hold_seconds
        self._terminal_since: float | None = None
        self._returned = False

    def poll(self, state: FT8QsoState, now: float) -> bool:
        """Return true once when terminal state has lasted through its hold."""
        if state not in _TERMINAL_STATES:
            self.reset()
            return False
        if self._terminal_since is None:
            self._terminal_since = now
            self._returned = False
            return False
        if self._returned or now - self._terminal_since < self._hold_seconds:
            return False
        self._returned = True
        return True

    def reset(self) -> None:
        """Clear terminal timing when a new or idle QSO lifecycle is observed."""
        self._terminal_since = None
        self._returned = False
