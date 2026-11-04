"""Physical callsign-cancel gesture for toggling the Tron listener."""

from __future__ import annotations

from collections.abc import Callable
from time import monotonic

from rolling_thunder.physical_controls import ControlAction, ControlInputEvent


class TronCancelTriplePress:
    """Toggle Tron on three eligible physical discard presses within two seconds.

    The interceptor always returns None so ordinary discard still runs for every
    press. It is called on the Tk thread by ControlDispatcher.
    """

    def __init__(
        self,
        on_toggle: Callable[[], None],
        *,
        allowed: Callable[[], bool] = lambda: True,
        clock: Callable[[], float] = monotonic,
        max_interval_s: float = 2.0,
    ) -> None:
        if max_interval_s <= 0:
            raise ValueError("max_interval_s must be positive")
        self._on_toggle = on_toggle
        self._allowed = allowed
        self._clock = clock
        self._max_interval_s = max_interval_s
        self._press_count = 0
        self._last_press_at: float | None = None

    def intercept(
        self,
        _event: ControlInputEvent,
        action: ControlAction,
    ) -> bool | None:
        """Observe validated actions and toggle after a guarded triple press."""
        if action is not ControlAction.DISCARD:
            self.reset()
            return None
        if not self._allowed():
            self.reset()
            return None

        now = self._clock()
        if (
            self._last_press_at is None
            or now < self._last_press_at
            or now - self._last_press_at > self._max_interval_s
        ):
            self._press_count = 1
        else:
            self._press_count += 1
        self._last_press_at = now

        if self._press_count == 3:
            self.reset()
            self._on_toggle()
        return None

    def reset(self) -> None:
        """Forget a partial gesture."""
        self._press_count = 0
        self._last_press_at = None