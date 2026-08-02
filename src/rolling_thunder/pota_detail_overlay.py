"""UI-independent timed controller for the POTA park-detail overlay."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from rolling_thunder.context_navigation import ContextId, ContextNavigationController
from rolling_thunder.pota_enrichment import (
    CallsignProfileSnapshot,
    ParkDetailSnapshot,
    PotaEnrichmentService,
)
from rolling_thunder.pota_spots import ParkReference, PotaSpot


class SelectedPotaSpotProvider(Protocol):
    """Expose the currently selected typed POTA spot."""

    @property
    def selected_spot(self) -> PotaSpot | None:
        """Return the selected spot or none when no row has focus."""
        ...


@dataclass(frozen=True)
class PotaDetailOverlayState:
    """Immutable state consumed by the right-side presentation area."""

    visible: bool
    activator: str | None = None
    park: ParkReference | None = None
    snapshot: ParkDetailSnapshot | None = None
    profile: CallsignProfileSnapshot | None = None


def _utc_now() -> datetime:
    return datetime.now(UTC)


class PotaDetailOverlayController:
    """Show selected park details temporarily without performing network I/O."""

    def __init__(
        self,
        context_navigation: ContextNavigationController,
        selected_spot_provider: SelectedPotaSpotProvider,
        enrichment: PotaEnrichmentService,
        *,
        duration: timedelta = timedelta(seconds=20),
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if duration <= timedelta(0):
            raise ValueError("POTA detail overlay duration must be positive.")
        self._context_navigation = context_navigation
        self._selected_spot_provider = selected_spot_provider
        self._enrichment = enrichment
        self._duration = duration
        self._clock = clock
        self._selected_spot: PotaSpot | None = None
        self._initial_snapshot: ParkDetailSnapshot | None = None
        self._expires_at: datetime | None = None

    @property
    def state(self) -> PotaDetailOverlayState:
        """Return current overlay state, expiring or dismissing it safely."""
        if self._context_navigation.state.selected is not ContextId.POTA:
            self.hide()
            return PotaDetailOverlayState(visible=False)

        now = self._aware_now()
        if self._expires_at is None or now >= self._expires_at:
            self.hide()
            return PotaDetailOverlayState(visible=False)

        selected_spot = self._selected_spot
        if selected_spot is None:
            return PotaDetailOverlayState(visible=False)

        snapshot = self._enrichment.get_park_detail(
            selected_spot.park.reference
        )
        profile = self._enrichment.get_callsign_profile(
            selected_spot.activator
        )
        return PotaDetailOverlayState(
            visible=True,
            activator=selected_spot.activator,
            park=selected_spot.park,
            snapshot=snapshot or self._initial_snapshot,
            profile=profile,
        )

    def show_selected(self) -> bool:
        """Request selected park/operator details and show the timed overlay."""
        if self._context_navigation.state.selected is not ContextId.POTA:
            return False
        selected_spot = self._selected_spot_provider.selected_spot
        if selected_spot is None:
            return False

        self._selected_spot = selected_spot
        self._initial_snapshot = self._enrichment.request_park_detail(
            selected_spot.park
        )
        self._enrichment.request_callsign_photo(selected_spot.activator)
        self._expires_at = self._aware_now() + self._duration
        return True

    def hide(self) -> bool:
        """Dismiss the overlay immediately without changing cached data."""
        was_visible = self._expires_at is not None
        self._selected_spot = None
        self._initial_snapshot = None
        self._expires_at = None
        return was_visible

    def _aware_now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("POTA overlay clock must be timezone-aware.")
        return now.astimezone(UTC)
