"""Safe UI-thread Tron intent dispatch through existing dashboard controls.

The caller MUST invoke dispatch_tron_intent on Tk's owning thread. This
module never authorizes a QSO, controls RF, commits contacts, or edits settings.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from rolling_thunder.context_navigation import ContextId, ContextNavigationController
from rolling_thunder.tron_commands import TronIntent

_NAV_TARGETS = {
    "dashboard": ContextId.POTA,
    "pota": ContextId.POTA,
    "dx": ContextId.DX,
    "browse": ContextId.BROWSE,
    "ft8": ContextId.FT8,
    "weather": ContextId.WEATHER,
    "repeaters": ContextId.REPEATERS,
    "dmr": ContextId.DMR,
    "log": ContextId.LOG,
    "settings": ContextId.SETTINGS,
}
_STATION_CONTEXTS = frozenset(
    {ContextId.POTA, ContextId.DX, ContextId.FT8, ContextId.REPEATERS}
)
_MAX_EDGE_STEPS = 64


class VoicePanelCommands(Protocol):
    """Selection-only subset of the existing active-panel controller."""

    def move_previous(self) -> bool: ...
    def move_next(self) -> bool: ...
    def has_station_selection(self) -> bool: ...
    def select_station(self) -> bool: ...


def dispatch_tron_intent(
    intent: TronIntent,
    navigation: ContextNavigationController,
    *,
    on_context_changed: Callable[[ContextId], None] | None = None,
    panel_commands: VoicePanelCommands | None = None,
) -> str | None:
    """Run one approved voice request on the UI thread and return feedback."""
    if intent.action == "help":
        return (
            "Say Tron status, current screen, show POTA, DX, Browse, FT8, Weather, "
            "Repeaters, DMR, log, or settings. Say next, previous, first station, "
            "last station, or select station. Use the physical controls to approve or reject a QSO."
        )
    if intent.action == "status":
        return f"Current screen: {navigation.state.definition.label}."
    if intent.action == "current_screen":
        return navigation.state.definition.label
    if intent.action == "navigate" and intent.target is not None:
        destination = _NAV_TARGETS.get(intent.target)
        if destination is None or destination not in {
            definition.context_id for definition in navigation.definitions
        }:
            return None
        navigation.select(destination)
        if on_context_changed is not None:
            on_context_changed(destination)
        return f"Showing {navigation.state.definition.label}."

    if panel_commands is None:
        return None
    context = navigation.state.selected
    if intent.action in {"next", "previous"}:
        if context in _STATION_CONTEXTS:
            moved = (
                panel_commands.move_next()
                if intent.action == "next"
                else panel_commands.move_previous()
            )
            return "Moved to the next station." if moved and intent.action == "next" else (
                "Moved to the previous station." if moved else "No station movement available."
            )
        if context is ContextId.WEATHER:
            moved = (
                panel_commands.move_next()
                if intent.action == "next"
                else panel_commands.move_previous()
            )
            return "Moved to the next weather alert." if moved and intent.action == "next" else (
                "Moved to the previous weather alert." if moved else "No weather alert movement available."
            )
        return "Station movement is unavailable on this screen."

    if intent.action in {"first", "last"}:
        if context not in _STATION_CONTEXTS:
            return "Station list movement is unavailable on this screen."
        step = panel_commands.move_previous if intent.action == "first" else panel_commands.move_next
        moved = False
        reached_edge = False
        for _ in range(_MAX_EDGE_STEPS):
            if not step():
                reached_edge = True
                break
            moved = True
        edge = "first" if intent.action == "first" else "last"
        if not moved and not panel_commands.has_station_selection():
            return "No station is available."
        if not reached_edge:
            return f"Moved toward the {edge} station; stopped at the 64-step safety limit."
        return f"Selected the {edge} station."

    if intent.action == "select_station":
        if context not in _STATION_CONTEXTS:
            return "Station selection is unavailable on this screen."
        if panel_commands.select_station():
            return "Station highlighted. Use the physical controls to approve or reject the QSO."
        return "No station is available to highlight."
    return None
