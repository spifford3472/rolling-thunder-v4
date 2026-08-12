"""Pure bounded mobile presentation for the six-meter repeater panel."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from rolling_thunder.repeater_active_override_controller import RepeaterActiveOverrideStatus
from rolling_thunder.repeater_configuration import (
    RepeaterConfigurationStatus,
    RepeaterConfigurationStatusKind,
)
from rolling_thunder.repeater_panel import (
    RepeaterDisplayFilter,
    RepeaterPanelRow,
    RepeaterPanelState,
)

_DEFAULT_MAX_ROWS = 3


@dataclass(frozen=True, slots=True)
class RepeaterCard:
    line1: str
    line2: str
    line3: str
    line4: str
    selected: bool
    active: bool


@dataclass(frozen=True, slots=True)
class RepeaterViewport:
    title: str
    status_line: str
    detail_line: str
    footer_line: str
    cards: tuple[RepeaterCard, ...]
    hidden_above_count: int
    hidden_below_count: int

    @property
    def has_cards(self) -> bool:
        return bool(self.cards)


def build_repeater_viewport(
    state: RepeaterPanelState,
    persistence: RepeaterActiveOverrideStatus | None = None,
    configuration: RepeaterConfigurationStatus | None = None,
    *,
    max_rows: int = _DEFAULT_MAX_ROWS,
) -> RepeaterViewport:
    """Build a truthful three-card repeater viewport with distinct action statuses."""
    if max_rows < 1:
        raise ValueError("repeater panel row limit must be positive")

    selected_index = next(
        (index for index, row in enumerate(state.rows) if row.selected),
        None,
    )
    total = len(state.rows)
    if selected_index is None:
        start = 0
    else:
        start = max(0, selected_index - max_rows + 1)
        start = min(start, max(0, total - max_rows))
    end = min(total, start + max_rows)

    filter_label = (
        "ACTIVE" if state.display_filter is RepeaterDisplayFilter.ACTIVE_ONLY else "ALL"
    )
    source_status = state.nearby_kind.value.replace("_", " ").upper()
    status_line = f"{source_status} — {total} SHOWN — FILTER {filter_label}"
    detail_line = state.source_error or state.nearby_detail

    footer_line = _footer(state, persistence, configuration)

    return RepeaterViewport(
        title=f"6 M REPEATERS — {filter_label}",
        status_line=status_line,
        detail_line=detail_line,
        footer_line=footer_line,
        cards=tuple(_card(row) for row in state.rows[start:end]),
        hidden_above_count=start,
        hidden_below_count=max(0, total - end),
    )


def _footer(
    state: RepeaterPanelState,
    persistence: RepeaterActiveOverrideStatus | None,
    configuration: RepeaterConfigurationStatus | None,
) -> str:
    if configuration is not None:
        if configuration.kind is RepeaterConfigurationStatusKind.CONFIGURING:
            return "CONFIGURING SELECTED REPEATER…"
        if configuration.kind is RepeaterConfigurationStatusKind.MANUAL_HANDOFF:
            outcome = configuration.outcome
            if outcome is not None and outcome.manual_handoff:
                return f"MANUAL HANDOFF — {outcome.manual_handoff}"
            return "REPEATER REQUIRES MANUAL CONFIGURATION"
        if configuration.kind is RepeaterConfigurationStatusKind.FAILED:
            return f"REPEATER CONFIG FAILED — {configuration.last_error or 'UNKNOWN ERROR'}"
        if configuration.kind is RepeaterConfigurationStatusKind.CONFIGURED:
            return "REPEATER CONFIGURED — VERIFY ANTENNA/TUNING BEFORE TRANSMIT"

    if state.radio_staged_action is not None:
        return "STAGED — PRESS ENCODER AGAIN TO CONFIGURE — BACK CANCELS"
    if persistence is not None and persistence.saving:
        return "SAVING ACTIVE OVERRIDE…"
    if persistence is not None and persistence.last_error:
        return f"ACTIVE SAVE FAILED — {persistence.last_error}"
    if state.staged_action is not None:
        return "ACTIVE CHANGE PREPARING…"

    next_filter = (
        "SHOW ALL"
        if state.display_filter is RepeaterDisplayFilter.ACTIVE_ONLY
        else "ACTIVE ONLY"
    )
    return f"ENCODER PRESS TO STAGE — BTN1 {next_filter} — BTN2 TOGGLE ACTIVE"


def _card(row: RepeaterPanelRow) -> RepeaterCard:
    record = row.repeater
    direction = record.shift_direction.value
    shift = f"{record.offset_hz / 1_000_000:.3f}"
    if direction == "minus":
        shift = f"-{shift}"
    elif direction == "plus":
        shift = f"+{shift}"
    else:
        shift = "SIMPLEX"

    tone_tx = _tone(record.tx_tone_hz)
    tone_rx = _tone(record.rx_tone_hz)
    state_text = "ACTIVE" if row.effective_active else "INACTIVE"
    return RepeaterCard(
        line1=record.name,
        line2=f"{record.rx_frequency.hz / 1_000_000:.3f} MHz  SHIFT {shift}",
        line3=f"TX TONE {tone_tx}  RX TONE {tone_rx}",
        line4=f"{row.distance_miles:.1f} mi  {state_text}",
        selected=row.selected,
        active=row.effective_active,
    )


def _tone(value: Decimal | None) -> str:
    if value is None:
        return "NONE"
    return str(value)
