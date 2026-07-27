"""Stateful controller connecting runtime POTA snapshots to presentation state."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from rolling_thunder.domain import RadioMode
from rolling_thunder.pota_dashboard_state import (
    PotaDashboardState,
    build_pota_dashboard_state,
)
from rolling_thunder.pota_spot_service import PotaSpotServiceState
from rolling_thunder.pota_spots import AmateurBand


class PotaSpotStateProvider(Protocol):
    """Provide the latest immutable POTA service snapshot."""

    @property
    def latest_pota_spot_state(self) -> PotaSpotServiceState | None:
        """Return the latest POTA state, or none when the feature is disabled."""
        ...


def _utc_now() -> datetime:
    """Return the current timezone-aware UTC time."""
    return datetime.now(UTC)


class PotaDashboardController:
    """Retain explicit POTA filters and build fresh immutable dashboard state."""

    def __init__(
        self,
        provider: PotaSpotStateProvider,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._provider = provider
        self._clock = clock
        self._band: AmateurBand | None = None
        self._mode: RadioMode | None = None

    @property
    def selected_band(self) -> AmateurBand | None:
        """Return the currently selected band filter."""
        return self._band

    @property
    def selected_mode(self) -> RadioMode | None:
        """Return the currently selected mode filter."""
        return self._mode

    @property
    def state(self) -> PotaDashboardState:
        """Build display state from the provider's latest snapshot and filters."""
        return build_pota_dashboard_state(
            self._provider.latest_pota_spot_state,
            band=self._band,
            mode=self._mode,
            reference_time=self._clock(),
        )

    def select_band(self, band: AmateurBand | None) -> PotaDashboardState:
        """Set or clear the band filter and return refreshed display state."""
        self._band = band
        return self.state

    def select_mode(self, mode: RadioMode | None) -> PotaDashboardState:
        """Set or clear the mode filter and return refreshed display state."""
        self._mode = mode
        return self.state

    def clear_filters(self) -> PotaDashboardState:
        """Clear all POTA filters and return refreshed display state."""
        self._band = None
        self._mode = None
        return self.state
