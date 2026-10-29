"""Bounded dispatch gate for source-validated RTCTRL/2 physical events."""

import math
import re
from collections.abc import Callable
from threading import Lock
from time import monotonic

from rolling_thunder.physical_controls import ControlInputEvent


class RecoveryControlEventGate:
    """Use current published session plus one watermark, never an all-ID set."""

    def __init__(
        self,
        inputs: frozenset[str],
        current_session: Callable[[], str | None],
        repeat_suppression_s: float,
        *,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if not math.isfinite(repeat_suppression_s) or repeat_suppression_s < 0:
            raise ValueError("Invalid repeat suppression interval")
        self._inputs = inputs
        self._current = current_session
        self._repeat = repeat_suppression_s
        self._clock = clock
        self._lock = Lock()
        self._session: str | None = None
        self._watermark = 0
        self._last: dict[str, float] = {}

    def accept(self, event: ControlInputEvent) -> bool:
        """Require a still-current healthy session and suppress repeated presses."""
        match = re.fullmatch(r"([0-9a-f]{32}):([1-9][0-9]{0,19})", event.event_id)
        if match is None or event.input_id not in self._inputs:
            return False
        nonce, sequence_text = match.groups()
        sequence = int(sequence_text)
        if sequence > 2**64 - 1:
            return False
        now = self._clock()
        if not math.isfinite(now) or event.expires_at_s is None or now >= event.expires_at_s:
            return False
        with self._lock:
            if nonce != self._current():
                return False
            if nonce != self._session:
                self._session, self._watermark = nonce, 0
            if sequence <= self._watermark:
                return False
            self._watermark = sequence
            last = self._last.get(event.input_id)
            if last is not None and (now < last or now - last < self._repeat):
                return False
            self._last[event.input_id] = now
            return True
