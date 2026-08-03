"""Stateful controller connecting runtime POTA snapshots to presentation state."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from rolling_thunder.domain import Frequency, RadioMode
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
    PotaModeFilter,
    PotaSpot,
    filter_pota_spots,
    frequency_band,
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
        maximum_spot_age: timedelta | None = None,
    ) -> None:
        self._provider = provider
        self._clock = clock
        self._maximum_spot_age = self._validated_maximum_age(maximum_spot_age)
        self._band: AmateurBand | None = None
        self._mode: RadioMode | None = None
        self._mode_filter = PotaModeFilter.ALL
        self._selected_index: int | None = None
        self._tune_intent: PotaTuneIntent | None = None

    @property
    def selected_band(self) -> AmateurBand | None:
        """Return the currently selected band filter."""
        return self._band

    @property
    def selected_mode(self) -> RadioMode | None:
        """Return the legacy exact radio-mode filter, if one was requested."""
        return self._mode

    @property
    def selected_mode_filter(self) -> PotaModeFilter:
        """Return the operator-facing POTA mode group."""
        return self._mode_filter

    @property
    def selected_index(self) -> int | None:
        """Return the selected ranked row index, if any."""
        return self._selected_index

    @property
    def tune_intent(self) -> PotaTuneIntent | None:
        """Return the current operator-created tune intent, if any."""
        return self._tune_intent

    @property
    def selected_spot(self) -> PotaSpot | None:
        """Return the currently selected typed spot from the live filtered view."""
        return self._selected_spot(self._clock())

    @property
    def visible_spots(self) -> tuple[PotaSpot, ...]:
        """Return the current filtered and ranked typed spot snapshot."""
        return self._visible_spots(self._clock())

    def set_maximum_spot_age(
        self,
        maximum_spot_age: timedelta | None,
    ) -> PotaDashboardState:
        """Apply or clear deterministic spot-age filtering."""
        self._maximum_spot_age = self._validated_maximum_age(maximum_spot_age)
        self._selected_index = None
        self._tune_intent = None
        return self.state

    @property
    def state(self) -> PotaDashboardState:
        """Build display state and clamp selection to its current rows."""
        reference_time = self._clock()
        dashboard = self._build_state(reference_time)

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

        return self._build_state(reference_time, selected_index=self._selected_index)

    def activate_for_frequency(self, frequency: Frequency | None) -> PotaDashboardState:
        """Default a newly selected POTA panel to the radio's current band."""
        band = frequency_band(frequency) if frequency is not None else None
        if band is not None:
            self._band = band
        self._selected_index = None
        self._tune_intent = None
        return self.state

    def select_band(self, band: AmateurBand | None) -> PotaDashboardState:
        """Set or clear the band filter and return refreshed display state."""
        self._band = band
        self._selected_index = None
        self._tune_intent = None
        return self.state

    def select_mode(self, mode: RadioMode | None) -> PotaDashboardState:
        """Preserve the legacy exact mode-filter command for existing callers."""
        self._mode = mode
        if mode is None:
            self._mode_filter = PotaModeFilter.ALL
        elif mode in {RadioMode.LSB, RadioMode.USB}:
            self._mode_filter = PotaModeFilter.SSB_PHONE
        elif mode is RadioMode.CW:
            self._mode_filter = PotaModeFilter.CW
        elif mode is RadioMode.DATA:
            self._mode_filter = PotaModeFilter.DATA
        else:
            self._mode_filter = PotaModeFilter.ALL
        self._selected_index = None
        self._tune_intent = None
        return self.state

    def select_mode_filter(self, mode_filter: PotaModeFilter) -> PotaDashboardState:
        """Set the operator-facing mode group and clear exact-mode filtering."""
        self._mode_filter = mode_filter
        self._mode = None
        self._selected_index = None
        self._tune_intent = None
        return self.state

    def clear_filters(self) -> PotaDashboardState:
        """Clear all POTA filters."""
        self._band = None
        self._mode = None
        self._mode_filter = PotaModeFilter.ALL
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

    def confirm_tune_intent(self) -> PotaTuneIntent | None:
        """Confirm only a pending intent that still matches selection."""
        intent = self._tune_intent
        if intent is None or intent.status is not PotaTuneIntentStatus.PENDING_CONFIRMATION:
            return intent

        selected_spot = self._selected_spot(self._clock())
        if selected_spot is None or not self._intent_matches_spot(
            intent,
            selected_spot,
        ):
            self._tune_intent = None
            return None

        self._tune_intent = intent.confirm()
        return self._tune_intent

    def cancel_tune_intent(self) -> PotaTuneIntent | None:
        """Cancel staged or confirmed intent without radio access."""
        if self._tune_intent is None:
            return None
        self._tune_intent = self._tune_intent.cancel()
        return self._tune_intent

    @staticmethod
    def _intent_matches_spot(
        intent: PotaTuneIntent,
        spot: PotaSpot,
    ) -> bool:
        """Return whether intent still identifies the selected typed spot."""
        return (
            intent.activator == spot.activator
            and intent.park_reference == spot.park.reference
            and intent.frequency == spot.frequency
            and intent.mode is spot.mode
        )

    @staticmethod
    def _validated_maximum_age(value: timedelta | None) -> timedelta | None:
        if value is not None and value < timedelta(0):
            raise ValueError("POTA maximum spot age must not be negative.")
        return value

    def _build_state(
        self,
        reference_time: datetime,
        *,
        selected_index: int | None = None,
    ) -> PotaDashboardState:
        return build_pota_dashboard_state(
            self._provider.latest_pota_spot_state,
            band=self._band,
            mode=self._mode,
            mode_filter=self._mode_filter,
            reference_time=reference_time,
            maximum_age=self._maximum_spot_age,
            selected_index=selected_index,
        )

    def _visible_spots(
        self,
        reference_time: datetime,
    ) -> tuple[PotaSpot, ...]:
        source_state = self._provider.latest_pota_spot_state
        if source_state is None:
            return ()

        filtered = filter_pota_spots(
            list(source_state.spots),
            band=self._band,
            mode=self._mode,
            mode_filter=self._mode_filter,
            reference_time=reference_time,
            maximum_age=self._maximum_spot_age,
        )
        ranked = rank_pota_spots(
            filtered,
            PotaSpotRankingCriteria(
                reference_time=reference_time,
                preferred_band=self._band,
                preferred_mode=self._mode,
            ),
        )
        return tuple(item.spot for item in ranked)

    def _selected_spot(self, reference_time: datetime) -> PotaSpot | None:
        """Resolve selection against the current filtered ranked snapshot."""
        if self._selected_index is None:
            return None

        visible_spots = self._visible_spots(reference_time)
        if self._selected_index >= len(visible_spots):
            return None
        return visible_spots[self._selected_index]
