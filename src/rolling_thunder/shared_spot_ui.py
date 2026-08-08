"""Pure bounded mobile presentation for the shared POTA/DX spot panel."""

from __future__ import annotations

from dataclasses import dataclass

from rolling_thunder.forge_client import ForgeRemoteProviderStatus
from rolling_thunder.shared_spot_panel import SharedSpotPanelRow, SharedSpotPanelState
from rolling_thunder.spot_domain import SpotProvider

_DEFAULT_MAX_ROWS = 3


@dataclass(frozen=True, slots=True)
class SharedSpotCard:
    """Four compact text lines for one mobile spot card."""

    line1: str
    line2: str
    line3: str
    line4: str
    selected: bool


@dataclass(frozen=True, slots=True)
class SharedSpotViewport:
    """Bounded shared-panel presentation consumed by Tkinter."""

    title: str
    status_line: str
    detail_line: str
    error_line: str
    cards: tuple[SharedSpotCard, ...]
    hidden_above_count: int
    hidden_below_count: int

    @property
    def has_cards(self) -> bool:
        """Return whether the current provider view has presentable rows."""
        return bool(self.cards)


def build_shared_spot_viewport(
    state: SharedSpotPanelState,
    *,
    max_rows: int = _DEFAULT_MAX_ROWS,
) -> SharedSpotViewport:
    """Build a provider-neutral three-card mobile viewport."""
    if max_rows < 1:
        raise ValueError("shared spot panel row limit must be positive")

    selected_index = next(
        (index for index, row in enumerate(state.rows) if row.selected),
        None,
    )
    total_rows = len(state.rows)
    if selected_index is None:
        start_index = 0
    else:
        start_index = max(0, selected_index - max_rows + 1)
        start_index = min(start_index, max(0, total_rows - max_rows))

    end_index = min(total_rows, start_index + max_rows)
    cards = tuple(_card_from_row(row) for row in state.rows[start_index:end_index])

    provider_label = state.provider.value.upper()
    health = state.provider_health
    health_label = health.status.value.upper() if health is not None else "UNKNOWN"
    status_line = (
        f"{state.status_label} — {provider_label} {total_rows} SPOTS"
        f" — PROVIDER {health_label}"
    )

    detail_line = _detail_line(state)
    error_parts = [text for text in (state.source_error, _provider_error(state)) if text]
    error_line = " — ".join(error_parts)

    return SharedSpotViewport(
        title=state.filter_label,
        status_line=status_line,
        detail_line=detail_line,
        error_line=error_line,
        cards=cards,
        hidden_above_count=start_index,
        hidden_below_count=max(0, total_rows - end_index),
    )


def _detail_line(state: SharedSpotPanelState) -> str:
    if not state.source_enabled:
        return "Shared Forge spots are disabled in this configuration."
    if not state.has_usable_snapshot:
        return "Waiting for the first valid shared Forge snapshot."
    generated = state.generated_at
    generated_text = generated.strftime("%H:%M:%SZ") if generated is not None else "UNKNOWN"
    revision = state.snapshot_revision if state.snapshot_revision is not None else "UNKNOWN"
    return f"SNAPSHOT {revision} — GENERATED {generated_text}"


def _provider_error(state: SharedSpotPanelState) -> str | None:
    health = state.provider_health
    if health is None or health.status in {
        ForgeRemoteProviderStatus.HEALTHY,
        ForgeRemoteProviderStatus.STARTING,
    }:
        return None
    return health.last_error or f"{health.provider.value.upper()} provider {health.status.value}"


def _card_from_row(row: SharedSpotPanelRow) -> SharedSpotCard:
    if row.provider is SpotProvider.POTA:
        park_reference = row.park_reference or "<UNKNOWN>"
        park_name = row.park_name or "<UNKNOWN>"
        location = row.location_code or "<UNKNOWN>"
        return SharedSpotCard(
            line1=_name_line(row),
            line2=_frequency_line(row),
            line3=f"{park_reference} - {park_name}",
            line4=location,
            selected=row.selected,
        )

    metadata = "  ".join(
        f"{item.key.upper()} {item.value}" for item in row.source_metadata[:2]
    )
    return SharedSpotCard(
        line1=_name_line(row),
        line2=_frequency_line(row),
        line3=f"GRID {row.grid_text}",
        line4=metadata or "SOURCE <UNKNOWN>",
        selected=row.selected,
    )


def _name_line(row: SharedSpotPanelRow) -> str:
    if row.operator_name is None:
        return row.callsign
    return f"{row.callsign} - {row.operator_name}"


def _frequency_line(row: SharedSpotPanelRow) -> str:
    return f"{row.frequency_text} MHz  {row.display_mode}  {row.age_minutes}m"
