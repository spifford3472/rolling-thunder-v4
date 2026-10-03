"""Presentation-safe controller for the experimental FT8 CQ browser."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from rolling_thunder.ft8.coordinator import FT8QsoResult
from rolling_thunder.ft8.domain import FT8CQActivity, FT8QsoContext, FT8QsoState
from rolling_thunder.ft8.receive import FT8ReceiveState


class FT8PanelMode(StrEnum):
    """High-level presentation mode for the FT8 workflow."""

    BROWSE = "browse"
    ACTIVE = "active"
    TERMINAL = "terminal"


@dataclass(frozen=True, slots=True)
class FT8PanelSnapshot:
    """Immutable presentation snapshot with no hardware capability."""

    mode: FT8PanelMode
    cq_activity: tuple[FT8CQActivity, ...]
    qso_state: FT8QsoState
    active_context: FT8QsoContext | None = None
    result: FT8QsoResult | None = None
    attempt_count: int = 0
    attempts_per_state: int = 0
    authorization_enabled: bool = False


class FT8PanelController:
    """Bridge UI intent to application-owned FT8 commands only."""

    def __init__(
        self,
        receive_state: Callable[[], FT8ReceiveState | None],
        qso_state: Callable[[], FT8QsoState],
        qso_context: Callable[[], FT8QsoContext | None],
        qso_result: Callable[[], FT8QsoResult | None],
        authorize: Callable[[FT8CQActivity], bool],
        abort: Callable[[], None],
        return_to_browser: Callable[[], FT8QsoResult | None],
        attempt_count: Callable[[], int] | None = None,
        attempts_per_state: Callable[[], int] | None = None,
        authorization_enabled: Callable[[], bool] | None = None,
    ) -> None:
        self._receive_state = receive_state
        self._qso_state = qso_state
        self._qso_context = qso_context
        self._qso_result = qso_result
        self._authorize = authorize
        self._abort = abort
        self._return_to_browser = return_to_browser
        self._attempt_count = attempt_count or (lambda: 0)
        self._attempts_per_state = attempts_per_state or (lambda: 0)
        self._authorization_enabled = authorization_enabled or (lambda: True)
        self._selected_callsign: str | None = None

    def snapshot(self) -> FT8PanelSnapshot:
        """Return current CQ browser/QSO presentation state without I/O."""
        receive = self._receive_state()
        cq_activity = () if receive is None else receive.cq_activity
        state = self._qso_state()
        result = self._qso_result()
        context = self._qso_context()

        if state in {
            FT8QsoState.COMPLETED,
            FT8QsoState.ABORTED,
            FT8QsoState.RETRY_EXHAUSTED,
            FT8QsoState.ERROR,
        }:
            mode = FT8PanelMode.TERMINAL
        elif state is FT8QsoState.IDLE:
            mode = FT8PanelMode.BROWSE
        else:
            mode = FT8PanelMode.ACTIVE

        if mode is FT8PanelMode.BROWSE:
            visible_callsigns = {activity.callsign for activity in cq_activity}
            if self._selected_callsign not in visible_callsigns:
                self._selected_callsign = None
        else:
            self._selected_callsign = None

        return FT8PanelSnapshot(
            mode=mode,
            cq_activity=cq_activity,
            qso_state=state,
            active_context=context,
            result=result,
            attempt_count=self._attempt_count(),
            attempts_per_state=self._attempts_per_state(),
            authorization_enabled=self._authorization_enabled(),
        )

    @property
    def selected_callsign(self) -> str | None:
        """Return the currently highlighted CQ callsign, if still visible."""
        self.snapshot()
        return self._selected_callsign

    def select_previous(self) -> str | None:
        """Move the CQ-browser cursor toward the previous visible station."""
        return self._move_selection(-1)

    def select_next(self) -> str | None:
        """Move the CQ-browser cursor toward the next visible station."""
        return self._move_selection(1)

    def visible_cq_activity(self, *, limit: int = 8) -> tuple[FT8CQActivity, ...]:
        """Return a selection-following CQ viewport without reordering activity."""
        if limit < 1:
            raise ValueError("FT8 CQ viewport limit must be at least 1")
        snapshot = self.snapshot()
        activity = snapshot.cq_activity
        if len(activity) <= limit:
            return activity

        selected = self._selected_callsign
        if selected is None:
            return activity[:limit]

        callsigns = tuple(item.callsign for item in activity)
        try:
            selected_index = callsigns.index(selected)
        except ValueError:
            return activity[:limit]

        start = max(0, selected_index - limit + 1)
        return activity[start : start + limit]

    def clear_selection(self) -> bool:
        """Clear a browse-only CQ highlight without changing QSO state."""
        if self.snapshot().mode is not FT8PanelMode.BROWSE or self._selected_callsign is None:
            return False
        self._selected_callsign = None
        return True

    def activate_selection(self) -> bool:
        """Request exactly the highlighted CQ station, if one exists."""
        snapshot = self.snapshot()
        if not snapshot.authorization_enabled:
            return False
        callsign = self.selected_callsign
        if callsign is None:
            return False
        return self.select_callsign(callsign)

    def select_callsign(self, callsign: str) -> bool:
        """Request exactly one currently visible CQ station."""
        snapshot = self.snapshot()
        if snapshot.mode is not FT8PanelMode.BROWSE:
            raise RuntimeError("cannot select another FT8 CQ while a QSO is active or terminal")

        normalized = callsign.strip().upper()
        matches = tuple(
            activity
            for activity in snapshot.cq_activity
            if activity.callsign == normalized
        )
        if len(matches) != 1:
            raise ValueError("selected FT8 CQ must identify exactly one current station")
        accepted = self._authorize(matches[0])
        if accepted:
            self._selected_callsign = None
        return accepted

    def _move_selection(self, direction: int) -> str | None:
        snapshot = self.snapshot()
        if snapshot.mode is not FT8PanelMode.BROWSE or not snapshot.cq_activity:
            return self._selected_callsign
        callsigns = tuple(activity.callsign for activity in snapshot.cq_activity)
        if self._selected_callsign is None:
            index = 0 if direction > 0 else len(callsigns) - 1
        else:
            current = callsigns.index(self._selected_callsign)
            index = max(0, min(len(callsigns) - 1, current + direction))
        self._selected_callsign = callsigns[index]
        return self._selected_callsign

    def abort(self) -> None:
        """Submit ABORT through the application-owned QSO service."""
        if self.snapshot().mode is FT8PanelMode.ACTIVE:
            self._abort()

    def return_to_browser(self) -> FT8QsoResult | None:
        """Clear one terminal QSO and restore CQ browsing."""
        if self.snapshot().mode is not FT8PanelMode.TERMINAL:
            raise RuntimeError("FT8 QSO must be terminal before returning to browser")
        return self._return_to_browser()
