"""Opt-in bounded UI timing and correlated slow-refresh diagnostics."""

from __future__ import annotations

import os
import sys
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from time import monotonic

from rolling_thunder.physical_controls import ControlAction

_PHASE_NAMES = (
    "pre_controls",
    "controls",
    "map_prepare",
    "map_update",
    "presentation",
    "context_widgets",
)

_SUBPHASE_NAMES = frozenset(
    {
        "radio_sync",
        "spot_tune_status",
        "repeater_persistence",
        "dmr_commits",
        "weather_update",
        "weather_alert_update",
        "weather_alert_viewport",
        "gps_snapshot",
        "map_controller",
        "map_viewport_request",
        "map_snapshot",
        "pota_viewport_request",
        "radar_viewport_request",
        "ft8_panel_snapshot",
        "ft8_receive_target",
        "ft8_receive_snapshot",
        "ft8_presentation",
        "base_plan",
        "base_b64",
        "base_photo",
        "base_canvas",
        "pota_canvas",
        "radar_plan",
        "radar_b64",
        "radar_photo",
        "radar_canvas",
        "overlay_status_canvas",
    }
)
_ACTION_NAMES = frozenset(action.value for action in ControlAction)


class UiTiming:
    """Observe major UI boundaries without influencing their behavior."""

    def __init__(
        self,
        enabled: bool = False,
        *,
        clock: Callable[[], float] = monotonic,
        report_every: int = 240,
        capacity: int = 256,
        slow_refresh_threshold_ms: float = 100.0,
        slow_report_interval_s: float = 1.0,
    ) -> None:
        if capacity <= 0 or report_every <= 0:
            raise ValueError("positive timing bounds required")
        if slow_refresh_threshold_ms <= 0 or slow_report_interval_s <= 0:
            raise ValueError("positive slow-refresh limits required")
        self.enabled = enabled
        self._clock = clock
        self._report_every = report_every
        self._samples: dict[str, deque[float]] = {
            name: deque(maxlen=capacity)
            for name in (
                "refresh",
                "controls",
                "map",
                "base_map",
                "radar",
                "refresh_gap",
            )
        }
        self._refreshes = 0
        self._previous_end: float | None = None
        self._next_refresh_id = 0
        self._active_refresh_id: int | None = None
        self._phase_started: float | None = None
        self._phase_durations: dict[str, float] = {}
        self._subphase_durations: dict[str, tuple[int, float, float]] = {}
        self._action_durations: dict[str, tuple[int, float, float]] = {}
        self._slow_refresh_threshold_ms = slow_refresh_threshold_ms
        self._slow_report_interval_s = slow_report_interval_s
        self._last_slow_report: float | None = None

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
        if self.enabled:
            if self._previous_end is not None:
                self._samples["refresh_gap"].append(
                    max(0.0, (started - self._previous_end) * 1000.0)
                )
            self._next_refresh_id += 1
            self._active_refresh_id = self._next_refresh_id
            self._phase_started = started
            self._phase_durations.clear()
            self._subphase_durations.clear()
            self._action_durations.clear()
        return started

    @contextmanager
    def subphase(self, name: str) -> Iterator[None]:
        """Measure one fixed, payload-free subphase without changing exceptions."""
        if name not in _SUBPHASE_NAMES:
            raise ValueError(f"unsupported UI timing subphase: {name}")
        if not self.enabled:
            yield
            return
        started = self._clock()
        try:
            yield
        finally:
            self.observe_subphase(name, started)

    def observe_subphase(self, name: str, started: float) -> None:
        """Accumulate count/total/max for one fixed subphase in this refresh."""
        if not self.enabled:
            return
        if name not in _SUBPHASE_NAMES:
            raise ValueError(f"unsupported UI timing subphase: {name}")
        self._accumulate(
            self._subphase_durations,
            name,
            max(0.0, (self._clock() - started) * 1000.0),
        )

    def observe_control_action(self, action_token: str, duration_ms: float) -> None:
        """Accumulate one typed action token; never record its source event."""
        if not self.enabled or self._active_refresh_id is None:
            return
        if action_token not in _ACTION_NAMES:
            raise ValueError("invalid UI timing action token")
        self._accumulate(
            self._action_durations,
            action_token,
            max(0.0, duration_ms),
        )

    @staticmethod
    def _accumulate(
        target: dict[str, tuple[int, float, float]],
        name: str,
        duration_ms: float,
    ) -> None:
        count, total, maximum = target.get(name, (0, 0.0, 0.0))
        target[name] = (count + 1, total + duration_ms, max(maximum, duration_ms))

    def checkpoint(self, name: str) -> None:
        """Record the elapsed portion of this refresh up to a named boundary."""
        if not self.enabled:
            return
        if name not in _PHASE_NAMES or name == "context_widgets":
            raise ValueError(f"unsupported UI timing phase: {name}")
        now = self._clock()
        if self._phase_started is None:
            return
        self._phase_durations[name] = max(
            0.0, (now - self._phase_started) * 1000.0
        )
        self._phase_started = now

    def end_refresh(self, started: float) -> None:
        if not self.enabled:
            return
        ended = self._clock()
        duration_ms = max(0.0, (ended - started) * 1000.0)
        if self._phase_started is not None:
            self._phase_durations["context_widgets"] = max(
                0.0, (ended - self._phase_started) * 1000.0
            )
        self._samples["refresh"].append(duration_ms)
        self._previous_end = ended
        self._refreshes += 1

        if duration_ms >= self._slow_refresh_threshold_ms:
            self._report_slow_refresh(ended, duration_ms)

        if self._refreshes % self._report_every:
            return
        for name, values in self._samples.items():
            if not values:
                continue
            ordered = sorted(values)
            index = min(
                len(ordered) - 1,
                max(0, (95 * len(ordered) + 99) // 100 - 1),
            )
            print(
                f"R1A_UI_TIMING metric={name} count={len(ordered)} "
                f"p95_ms={ordered[index]:.2f} max_ms={ordered[-1]:.2f}",
                file=sys.stderr,
                flush=True,
            )

    def _report_slow_refresh(self, ended: float, duration_ms: float) -> None:
        if (
            self._last_slow_report is not None
            and ended - self._last_slow_report < self._slow_report_interval_s
        ):
            return
        refresh_id = self._active_refresh_id
        if refresh_id is None:
            return
        phases = " ".join(
            f"{name}_ms={self._phase_durations.get(name, 0.0):.2f}"
            for name in _PHASE_NAMES
        )
        details = self._format_details(self._subphase_durations)
        actions = self._format_details(self._action_durations)
        print(
            f"R1C2_SLOW_REFRESH id={refresh_id} "
            f"duration_ms={duration_ms:.2f} {phases} "
            f"subphases={details} actions={actions}",
            file=sys.stderr,
            flush=True,
        )
        self._last_slow_report = ended

    @staticmethod
    def _format_details(values: dict[str, tuple[int, float, float]]) -> str:
        if not values:
            return "none"
        return ",".join(
            f"{name}:{count}:{total:.2f}:{maximum:.2f}"
            for name, (count, total, maximum) in sorted(values.items())
        )
