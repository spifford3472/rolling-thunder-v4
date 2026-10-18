"""Opt-in, bounded, monotonic UI timing aggregates; no identifiers or I/O on hot path."""

from __future__ import annotations

import os
import sys
from collections import deque
from collections.abc import Callable
from time import monotonic


class UiTiming:
    """Observe major UI boundaries without influencing their behavior."""

    def __init__(self, enabled: bool = False, *, clock: Callable[[], float] = monotonic,
                 report_every: int = 240, capacity: int = 256) -> None:
        if capacity <= 0 or report_every <= 0:
            raise ValueError("positive timing bounds required")
        self.enabled = enabled
        self._clock = clock
        self._report_every = report_every
        self._samples: dict[str, deque[float]] = {name: deque(maxlen=capacity) for name in
                         ("refresh", "controls", "map", "refresh_gap")}
        self._refreshes = 0
        self._previous_end: float | None = None

    @classmethod
    def from_environment(cls) -> UiTiming:
        return cls(enabled=os.environ.get("RT_R1A_UI_TIMING", "") == "1")

    def start(self) -> float:
        return self._clock() if self.enabled else 0.0

    def observe(self, name: str, started: float) -> None:
        if not self.enabled:
            return
        self._samples[name].append(max(0.0, (self._clock() - started) * 1000.0))

    def begin_refresh(self) -> float:
        started = self.start()
        if self.enabled and self._previous_end is not None:
            self._samples["refresh_gap"].append(max(0.0, (started - self._previous_end) * 1000.0))
        return started

    def end_refresh(self, started: float) -> None:
        if not self.enabled:
            return
        self.observe("refresh", started)
        self._previous_end = self._clock()
        self._refreshes += 1
        if self._refreshes % self._report_every:
            return
        for name, values in self._samples.items():
            if not values:
                continue
            ordered = sorted(values)
            index = min(len(ordered) - 1, max(0, (95 * len(ordered) + 99) // 100 - 1))
            print(  # systemd captures stderr without depending on root logger configuration
                f"R1A_UI_TIMING metric={name} count={len(ordered)} "
                f"p95_ms={ordered[index]:.2f} max_ms={ordered[-1]:.2f}",
                file=sys.stderr,
                flush=True,
            )
