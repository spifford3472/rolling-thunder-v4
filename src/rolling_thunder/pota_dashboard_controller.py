"""Stateful controller connecting runtime POTA snapshots to presentation state."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from rolling_thunder.domain import RadioMode
from rolling_thunder.pota_dashboard_state import (
    PotaDashboardState,
    build_pota_dashboard_state,
)
from rolling_thunder.pota_spot_ranking import (
    PotaSpotRankingCriteria,
    rank_pota_spots,
)
from rolling_thunder.pota_spot_service import PotaSpotServiceState
from rolling_thunder.pota_spots import (
    AmateurBand,
    PotaSpot,
    filter_pota_spots,
)
from rolling_thunder.pota_tune_intent import (
    PotaTuneIntent,
    PotaTuneIntentStatus,
)


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
        self._selected_index: int | None = None
        self._tune_intent: PotaTuneIntent | None = None

    @property
    def selected_band(self) -> AmateurBand | None:
        """Return the currently selected band filter."""
        return self._band

    @property
    def selected_mode(self) -> RadioMode | None:
        """Return the currently selected mode filter."""
        return self._mode

    @property
    def selected_index(self) -> int | None:
        """Return the selected ranked row index, if any."""
        return self._selected_index

    @property
    def tune_intent(self) -> PotaTuneIntent | None:
        """Return the current operator-created tune intent, if any."""
        return self._tune_intent

    @property
    def state(self) -> PotaDashboardState:
        """Build display state and clamp selection to its current rows."""
        reference_time = self._clock()
        dashboard = build_pota_dashboard_state(
            self._provider.latest_pota_spot_state,
            band=self._band,
            mode=self._mode,
            reference_time=reference_time,
        )

        previous_index = self._selected_index
        if not dashboard.rows:
            self._selected_index = None
        elif self._selected_index is not None:
            self._selected_index = min(
                self._selected_index,
                len(dashboard.rows) - 1,
            )

        if self._selected_index != previous_index:
            self._tune_intent = None

        return build_pota_dashboard_state(
            self._provider.latest_pota_spot_state,
            band=self._band,
            mode=self._mode,
            reference_time=reference_time,
            selected_index=self._selected_index,
        )

    def select_band(self, band: AmateurBand | None) -> PotaDashboardState:
        """Set or clear the band filter and return refreshed display state."""
        self._band = band
        self._selected_index = None
        self._tune_intent = None
        return self.state

    def select_mode(self, mode: RadioMode | None) -> PotaDashboardState:
        """Set or clear the mode filter and return refreshed display state."""
        self._mode = mode
        self._selected_index = None
        self._tune_intent = None
        return self.state

    def clear_filters(self) -> PotaDashboardState:
        """Clear all POTA filters and return refreshed display state."""
        self._band = None
        self._mode = None
        self._selected_index = None
        self._tune_intent = None
        return self.state

    def select_previous(self) -> PotaDashboardState:
        """Move selection toward the start without wrapping."""
        dashboard = self.state
        if not dashboard.rows:
            return dashboard

        previous_index = self._selected_index
        if self._selected_index is None:
            self._selected_index = len(dashboard.rows) - 1
        else:
            self._selected_index = max(0, self._selected_index - 1)

        if self._selected_index != previous_index:
            self._tune_intent = None
        return self.state

    def select_next(self) -> PotaDashboardState:
        """Move selection toward the end without wrapping."""
        dashboard = self.state
        if not dashboard.rows:
            return dashboard

        previous_index = self._selected_index
        if self._selected_index is None:
            self._selected_index = 0
        else:
            self._selected_index = min(
                len(dashboard.rows) - 1,
                self._selected_index + 1,
            )

        if self._selected_index != previous_index:
            self._tune_intent = None
        return self.state

    def clear_selection(self) -> PotaDashboardState:
        """Clear the current read-only spot selection and tune intent."""
        self._selected_index = None
        self._tune_intent = None
        return self.state

    def request_tune_intent(self) -> PotaTuneIntent | None:
        """Create pending intent from the explicitly selected typed spot."""
        created_at = self._clock()
        selected_spot = self._selected_spot(created_at)
        if selected_spot is None:
            self._tune_intent = None
            return None

        self._tune_intent = PotaTuneIntent(
            status=PotaTuneIntentStatus.PENDING_CONFIRMATION,
            activator=selected_spot.activator,
            park_reference=selected_spot.park.reference,
            frequency=selected_spot.frequency,
            mode=selected_spot.mode,
            created_at=created_at,
        )
        return self._tune_intent

    def cancel_tune_intent(self) -> PotaTuneIntent | None:
        """Cancel pending intent without calling a radio interface."""
        if self._tune_intent is None:
            return None
        self._tune_intent = self._tune_intent.cancel()
        return self._tune_intent

    def _selected_spot(self, reference_time: datetime) -> PotaSpot | None:
        """Resolve selection against the current filtered ranked snapshot."""
        source_state = self._provider.latest_pota_spot_state
        if source_state is None or self._selected_index is None:
            return None

        filtered = filter_pota_spots(
            list(source_state.spots),
            band=self._band,
            mode=self._mode,
        )
        ranked = rank_pota_spots(
            filtered,
            PotaSpotRankingCriteria(
                reference_time=reference_time,
                preferred_band=self._band,
                preferred_mode=self._mode,
            ),
        )
        if self._selected_index >= len(ranked):
            return None
        return ranked[self._selected_index].spot
