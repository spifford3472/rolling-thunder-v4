"""Typed context selection for the persistent dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final


class ContextId(StrEnum):
    """Stable identifiers for dashboard context panels."""

    POTA = "pota"
    DX = "dx"
    BROWSE = "browse"
    REPEATERS = "repeaters"
    AI = "ai"
    WEATHER = "weather"
    SETTINGS = "settings"
    LOG = "log"
    DMR = "dmr"
    FT8 = "ft8"


@dataclass(frozen=True)
class ContextDefinition:
    """Static presentation metadata for one context placeholder."""

    context_id: ContextId
    label: str
    shortcut: str
    title: str
    placeholder: str


CONTEXT_DEFINITIONS: Final[tuple[ContextDefinition, ...]] = (
    ContextDefinition(
        ContextId.POTA,
        "POTA",
        "1",
        "POTA",
        "Future POTA details here.",
    ),
    ContextDefinition(
        ContextId.DX,
        "DX",
        "2",
        "DX",
        "Future DX details here.",
    ),
    ContextDefinition(
        ContextId.BROWSE,
        "BROWSE",
        "b",
        "BROWSE",
        "Free-form receive tuning and contact logging.",
    ),
    ContextDefinition(
        ContextId.REPEATERS,
        "REPEATERS",
        "3",
        "REPEATERS",
        "Nearby 6 m repeaters from local deployment data.",
    ),
    ContextDefinition(
        ContextId.AI,
        "AI",
        "4",
        "AI ADVISOR",
        "Future AI advisor details here.",
    ),
    ContextDefinition(
        ContextId.WEATHER,
        "WEATHER",
        "6",
        "WEATHER",
        "Retained weather details here.",
    ),
    ContextDefinition(
        ContextId.SETTINGS,
        "SETTINGS",
        "5",
        "SETTINGS",
        "Future settings details here.",
    ),
    ContextDefinition(
        ContextId.LOG,
        "LOG",
        "7",
        "LOG",
        "Recent local Rolling Thunder contacts.",
    ),
    ContextDefinition(
        ContextId.DMR,
        "DMR",
        "8",
        "DMR HOTSPOT",
        "Live hotspot audio, caller history, and staged DMR logging.",
    ),
    ContextDefinition(
        ContextId.FT8,
        "FT8",
        "9",
        "FT8",
        "Native FT8 CQ browser and one-QSO operator workflow.",
    ),
)

_DEFINITIONS_BY_ID: Final[dict[ContextId, ContextDefinition]] = {
    definition.context_id: definition for definition in CONTEXT_DEFINITIONS
}
_SHORTCUTS: Final[dict[str, ContextId]] = {
    definition.shortcut: definition.context_id for definition in CONTEXT_DEFINITIONS
}


@dataclass(frozen=True)
class ContextNavigationState:
    """Current context selection exposed to the dashboard."""

    selected: ContextId = ContextId.POTA

    @property
    def definition(self) -> ContextDefinition:
        """Return presentation metadata for the selected context."""
        return _DEFINITIONS_BY_ID[self.selected]


class ContextNavigationController:
    """Own direct, persistent context selection."""

    def __init__(self, initial: ContextId = ContextId.POTA) -> None:
        self._state = ContextNavigationState(selected=initial)

    @property
    def state(self) -> ContextNavigationState:
        """Return the immutable current selection."""
        return self._state

    def select(self, context_id: ContextId) -> ContextNavigationState:
        """Select a context directly and return the updated state."""
        self._state = ContextNavigationState(selected=context_id)
        return self._state

    def select_shortcut(self, shortcut: str) -> bool:
        """Select a context by keyboard shortcut when recognized."""
        context_id = _SHORTCUTS.get(shortcut)
        if context_id is None:
            return False
        self.select(context_id)
        return True

    def select_next(self) -> ContextNavigationState:
        """Select the next context, wrapping to the first context."""
        context_ids = tuple(definition.context_id for definition in CONTEXT_DEFINITIONS)
        current_index = context_ids.index(self._state.selected)
        next_index = (current_index + 1) % len(context_ids)
        return self.select(context_ids[next_index])

    def select_home(self) -> ContextNavigationState:
        """Return to the primary POTA context."""
        return self.select(ContextId.POTA)
