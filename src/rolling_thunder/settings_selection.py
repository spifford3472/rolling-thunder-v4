"""Pure Settings-row selection domain."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar


class SettingsOption(StrEnum):
    """Stable Settings rows in operator-visible order."""

    MAP_ZOOM = "map_zoom"
    RADAR = "radar"
    CALLSIGN_INFO = "callsign_info"
    MAP_STYLE = "map_style"
    REBOOT = "reboot"
    SHUTDOWN = "shutdown"


@dataclass(frozen=True, slots=True)
class SettingsSelection:
    """Immutable clamped selection; Settings always has one highlighted row."""

    selected: SettingsOption = SettingsOption.MAP_ZOOM

    ORDER: ClassVar[tuple[SettingsOption, ...]] = tuple(SettingsOption)

    def __post_init__(self) -> None:
        if isinstance(self.selected, bool) or not isinstance(self.selected, SettingsOption):
            raise TypeError("Settings selection must be a SettingsOption.")

    @property
    def index(self) -> int:
        return self.ORDER.index(self.selected)

    def moved(self, delta: int) -> SettingsSelection:
        """Return a selection moved by an integer delta without wrapping."""
        if isinstance(delta, bool) or not isinstance(delta, int):
            raise TypeError("Settings movement must be an integer.")
        index = min(max(self.index + delta, 0), len(self.ORDER) - 1)
        return SettingsSelection(self.ORDER[index])


# Compatibility for the unaccepted issue-371 candidate.  SettingsOption is the
# public checkpoint name; this alias avoids creating a second enum identity.
SettingId = SettingsOption
