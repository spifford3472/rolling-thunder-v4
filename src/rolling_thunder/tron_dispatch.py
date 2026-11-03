"""Safe UI-thread Tron intent dispatch through existing context navigation.

The caller MUST invoke dispatch_tron_intent on Tk's owning thread. This
module never controls RF, callsign capture, or contact commits.
"""
from __future__ import annotations

from collections.abc import Callable

from rolling_thunder.context_navigation import ContextId, ContextNavigationController
from rolling_thunder.tron_commands import TronIntent

_NAV_TARGETS = {
    "dashboard": ContextId.POTA,
    "pota": ContextId.POTA,
    "dx": ContextId.DX,
    "ft8": ContextId.FT8,
    "log": ContextId.LOG,
    "settings": ContextId.SETTINGS,
}


def dispatch_tron_intent(
    intent: TronIntent,
    navigation: ContextNavigationController,
    *,
    on_context_changed: Callable[[ContextId], None] | None = None,
) -> str | None:
    """Return a concise response; unsupported destinations do nothing.

    Never call this function directly from an audio worker. Schedule it
    through the existing Tk main-loop polling mechanism instead.
    """
    if intent.action == "help":
        return "Say Tron status, Tron current screen, or Tron show POTA, DX, FT8, log, or settings."
    if intent.action == "status":
        return f"Current screen: {navigation.state.definition.label}."
    if intent.action == "current_screen":
        return navigation.state.definition.label
    if intent.action != "navigate" or intent.target is None:
        return None
    destination = _NAV_TARGETS.get(intent.target)
    if destination is None:
        return None
    if destination not in {definition.context_id for definition in navigation.definitions}:
        return None
    navigation.select(destination)
    if on_context_changed is not None:
        on_context_changed(destination)
    return f"Showing {navigation.state.definition.label}."
