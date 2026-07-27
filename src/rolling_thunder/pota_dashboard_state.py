"""Pure UI-facing presentation state for POTA spot data."""

from dataclasses import dataclass
from datetime import UTC, datetime

from rolling_thunder.domain import RadioMode
from rolling_thunder.pota_spot_ranking import (
    PotaSpotRankingCriteria,
    rank_pota_spots,
)
from rolling_thunder.pota_spot_service import PotaSpotServiceState
from rolling_thunder.pota_spot_source import PotaSpotSourceAvailability
from rolling_thunder.pota_spots import AmateurBand, PotaSpot, filter_pota_spots


@dataclass(frozen=True)
class PotaSpotRow:
    """Display-ready values for one POTA spot row."""

    activator: str
    park_reference: str
    park_name: str
    frequency: str
    mode: str
    spotted_at: str
    comments: str
    is_selected: bool


@dataclass(frozen=True)
class PotaDashboardState:
    """Immutable display state for a future POTA dashboard panel."""

    status: str
    detail: str
    availability: str
    is_stale: bool
    last_refresh: str
    error: str
    total_spot_count: int
    visible_spot_count: int
    rows: tuple[PotaSpotRow, ...]


def build_pota_dashboard_state(
    state: PotaSpotServiceState | None,
    *,
    band: AmateurBand | None = None,
    mode: RadioMode | None = None,
    reference_time: datetime | None = None,
    selected_index: int | None = None,
) -> PotaDashboardState:
    """Convert a service snapshot into stable display-ready POTA state."""
    if state is None:
        return PotaDashboardState(
            status="DISABLED",
            detail="POTA SPOTS DISABLED",
            availability="DISABLED",
            is_stale=False,
            last_refresh="—",
            error="",
            total_spot_count=0,
            visible_spot_count=0,
            rows=(),
        )

    spots = tuple(filter_pota_spots(list(state.spots), band=band, mode=mode))
    if reference_time is not None:
        spots = tuple(
            ranked.spot
            for ranked in rank_pota_spots(
                list(spots),
                PotaSpotRankingCriteria(
                    reference_time=reference_time,
                    preferred_band=band,
                    preferred_mode=mode,
                ),
            )
        )

    rows = tuple(
        _build_row(spot, is_selected=index == selected_index)
        for index, spot in enumerate(spots)
    )
    availability = state.availability.value.upper()
    last_refresh = _format_timestamp(state.last_success_at)
    error = state.last_error or ""

    if state.availability is PotaSpotSourceAvailability.UNKNOWN:
        status = "LOADING"
        detail = "POTA SPOTS NOT REFRESHED"
    elif state.is_stale:
        status = "STALE"
        detail = f"SHOWING {len(rows)} OF {len(state.spots)} RETAINED SPOTS"
    elif state.availability is PotaSpotSourceAvailability.UNAVAILABLE:
        status = "UNAVAILABLE"
        detail = "POTA SPOT SOURCE UNAVAILABLE"
    elif not state.spots:
        status = "EMPTY"
        detail = "NO CURRENT POTA SPOTS"
    else:
        status = "READY"
        detail = f"SHOWING {len(rows)} OF {len(state.spots)} SPOTS"

    return PotaDashboardState(
        status=status,
        detail=detail,
        availability=availability,
        is_stale=state.is_stale,
        last_refresh=last_refresh,
        error=error,
        total_spot_count=len(state.spots),
        visible_spot_count=len(rows),
        rows=rows,
    )


def _build_row(spot: PotaSpot, *, is_selected: bool = False) -> PotaSpotRow:
    return PotaSpotRow(
        activator=str(spot.activator),
        park_reference=spot.park.reference,
        park_name=spot.park.name or "—",
        frequency=f"{spot.frequency.hz / 1_000_000:.3f} MHz",
        mode=spot.mode.value,
        spotted_at=_format_timestamp(spot.spotted_at),
        comments=spot.comments or "",
        is_selected=is_selected,
    )


def _format_timestamp(value: datetime | None) -> str:
    if value is None:
        return "—"
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
