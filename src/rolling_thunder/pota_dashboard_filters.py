"""Keyboard-driven POTA dashboard filter commands."""

from dataclasses import dataclass

from rolling_thunder.domain import RadioMode
from rolling_thunder.pota_dashboard_controller import PotaDashboardController
from rolling_thunder.pota_dashboard_state import PotaDashboardState
from rolling_thunder.pota_spots import AmateurBand

_BANDS: tuple[AmateurBand | None, ...] = (None, *tuple(AmateurBand))
_MODES: tuple[RadioMode | None, ...] = (None, *tuple(RadioMode))


@dataclass(frozen=True)
class PotaDashboardFilterState:
    """Immutable operator-facing filter labels and dashboard state."""

    band_label: str
    mode_label: str
    dashboard: PotaDashboardState

    @property
    def display_line(self) -> str:
        """Return one compact line for the read-only POTA panel."""
        return f"FILTERS — BAND {self.band_label} — MODE {self.mode_label}"


class PotaDashboardFilterController:
    """Translate direct keyboard commands into explicit POTA filters."""

    def __init__(self, dashboard: PotaDashboardController) -> None:
        self._dashboard = dashboard

    @property
    def state(self) -> PotaDashboardFilterState:
        """Return current filter labels with a fresh dashboard snapshot."""
        return PotaDashboardFilterState(
            band_label=self._dashboard.selected_band.value
            if self._dashboard.selected_band is not None
            else "ALL",
            mode_label=self._dashboard.selected_mode.value
            if self._dashboard.selected_mode is not None
            else "ALL",
            dashboard=self._dashboard.state,
        )

    def handle_key(self, key: str) -> bool:
        """Handle one supported key and report whether it was consumed."""
        actions = {
            "[": self.previous_band,
            "]": self.next_band,
            ",": self.previous_mode,
            ".": self.next_mode,
            "/": self.clear,
        }
        action = actions.get(key)
        if action is None:
            return False
        action()
        return True

    def previous_band(self) -> PotaDashboardFilterState:
        """Select the previous supported band, wrapping through ALL."""
        current = _BANDS.index(self._dashboard.selected_band)
        self._dashboard.select_band(_BANDS[(current - 1) % len(_BANDS)])
        return self.state

    def next_band(self) -> PotaDashboardFilterState:
        """Select the next supported band, wrapping through ALL."""
        current = _BANDS.index(self._dashboard.selected_band)
        self._dashboard.select_band(_BANDS[(current + 1) % len(_BANDS)])
        return self.state

    def previous_mode(self) -> PotaDashboardFilterState:
        """Select the previous supported mode, wrapping through ALL."""
        current = _MODES.index(self._dashboard.selected_mode)
        self._dashboard.select_mode(_MODES[(current - 1) % len(_MODES)])
        return self.state

    def next_mode(self) -> PotaDashboardFilterState:
        """Select the next supported mode, wrapping through ALL."""
        current = _MODES.index(self._dashboard.selected_mode)
        self._dashboard.select_mode(_MODES[(current + 1) % len(_MODES)])
        return self.state

    def clear(self) -> PotaDashboardFilterState:
        """Clear both filters explicitly."""
        self._dashboard.clear_filters()
        return self.state
