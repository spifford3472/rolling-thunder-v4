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


class FT8PanelController:
    """Bridge UI intent to application-owned FT8 commands only."""

    def __init__(
        self,
        receive_state: Callable[[], FT8ReceiveState | None],
        qso_state: Callable[[], FT8QsoState],
        qso_context: Callable[[], FT8QsoContext | None],
        qso_result: Callable[[], FT8QsoResult | None],
        authorize: Callable[[FT8CQActivity], FT8QsoContext],
        abort: Callable[[], None],
        return_to_browser: Callable[[], FT8QsoResult | None],
    ) -> None:
        self._receive_state = receive_state
        self._qso_state = qso_state
        self._qso_context = qso_context
        self._qso_result = qso_result
        self._authorize = authorize
        self._abort = abort
        self._return_to_browser = return_to_browser

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

        return FT8PanelSnapshot(
            mode=mode,
            cq_activity=cq_activity,
            qso_state=state,
            active_context=context,
            result=result,
        )

    def select_callsign(self, callsign: str) -> FT8QsoContext:
        """Authorize exactly one currently visible CQ station."""
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
        return self._authorize(matches[0])

    def abort(self) -> None:
        """Submit ABORT through the application-owned QSO service."""
        if self.snapshot().mode is FT8PanelMode.ACTIVE:
            self._abort()

    def return_to_browser(self) -> FT8QsoResult | None:
        """Clear one terminal QSO and restore CQ browsing."""
        if self.snapshot().mode is not FT8PanelMode.TERMINAL:
            raise RuntimeError("FT8 QSO must be terminal before returning to browser")
        return self._return_to_browser()
