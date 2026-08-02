"""Operator-driven POTA dashboard filter commands."""

from dataclasses import dataclass

from rolling_thunder.domain import Frequency
from rolling_thunder.pota_dashboard_controller import PotaDashboardController
from rolling_thunder.pota_dashboard_state import PotaDashboardState
from rolling_thunder.pota_spots import AmateurBand, PotaModeFilter, frequency_band

_BANDS: tuple[AmateurBand, ...] = (
    AmateurBand.BAND_80M,
    AmateurBand.BAND_40M,
    AmateurBand.BAND_20M,
    AmateurBand.BAND_17M,
    AmateurBand.BAND_15M,
    AmateurBand.BAND_12M,
    AmateurBand.BAND_10M,
)
_MODES: tuple[PotaModeFilter, ...] = (
    PotaModeFilter.SSB_PHONE,
    PotaModeFilter.CW,
    PotaModeFilter.FT4,
    PotaModeFilter.FT8,
    PotaModeFilter.DATA,
    PotaModeFilter.ALL,
)
_DEFAULT_BAND = AmateurBand.BAND_20M


@dataclass(frozen=True)
class PotaDashboardFilterState:
    """Immutable operator-facing filter labels and dashboard state."""

    band_label: str
    mode_label: str
    dashboard: PotaDashboardState

    @property
    def display_line(self) -> str:
        """Return one compact header line for the POTA panel."""
        return f"POTA    BAND: {self.band_label}    MODE: {self.mode_label}"


class PotaDashboardFilterController:
    """Apply the fixed mobile POTA band and mode cycles."""

    def __init__(self, dashboard: PotaDashboardController) -> None:
        self._dashboard = dashboard
        self._dashboard.select_mode_filter(PotaModeFilter.SSB_PHONE)

    @property
    def state(self) -> PotaDashboardFilterState:
        """Return current filter labels with a fresh dashboard snapshot."""
        selected_band = self._dashboard.selected_band or _DEFAULT_BAND
        return PotaDashboardFilterState(
            band_label=selected_band.value.removesuffix("m"),
            mode_label=self._dashboard.selected_mode_filter.value,
            dashboard=self._dashboard.state,
        )

    def activate_for_frequency(self, frequency: Frequency | None) -> PotaDashboardFilterState:
        """Default the POTA panel to the radio's current supported band."""
        band = frequency_band(frequency) if frequency is not None else None
        if band not in _BANDS:
            band = _DEFAULT_BAND
        self._dashboard.select_band(band)
        return self.state

    def handle_key(self, key: str) -> bool:
        """Handle retained development keyboard shortcuts."""
        actions = {
            "[": self.previous_band,
            "]": self.next_band,
            ",": self.previous_mode,
            ".": self.next_mode,
            "/": self.reset_defaults,
        }
        action = actions.get(key)
        if action is None:
            return False
        action()
        return True

    def previous_band(self) -> PotaDashboardFilterState:
        """Select the previous mobile HF band with wraparound."""
        current = self._current_band_index()
        self._dashboard.select_band(_BANDS[(current - 1) % len(_BANDS)])
        return self.state

    def next_band(self) -> PotaDashboardFilterState:
        """Select the next mobile HF band with wraparound."""
        current = self._current_band_index()
        self._dashboard.select_band(_BANDS[(current + 1) % len(_BANDS)])
        return self.state

    def previous_mode(self) -> PotaDashboardFilterState:
        """Select the previous operator mode group with wraparound."""
        current = _MODES.index(self._dashboard.selected_mode_filter)
        self._dashboard.select_mode_filter(_MODES[(current - 1) % len(_MODES)])
        return self.state

    def next_mode(self) -> PotaDashboardFilterState:
        """Select the next operator mode group with wraparound."""
        current = _MODES.index(self._dashboard.selected_mode_filter)
        self._dashboard.select_mode_filter(_MODES[(current + 1) % len(_MODES)])
        return self.state

    def reset_defaults(self) -> PotaDashboardFilterState:
        """Restore the 20-meter SSB/PHONE mobile defaults."""
        self._dashboard.select_band(_DEFAULT_BAND)
        self._dashboard.select_mode_filter(PotaModeFilter.SSB_PHONE)
        return self.state

    def clear(self) -> PotaDashboardFilterState:
        """Compatibility alias for restoring mobile defaults."""
        return self.reset_defaults()

    def _current_band_index(self) -> int:
        selected = self._dashboard.selected_band
        if selected not in _BANDS:
            return _BANDS.index(_DEFAULT_BAND)
        return _BANDS.index(selected)
