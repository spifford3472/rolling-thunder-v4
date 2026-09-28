"""Tests for pure six-meter repeater mobile presentation."""

from decimal import Decimal

from rolling_thunder.domain import Frequency
from rolling_thunder.fm_repeater import (
    FmRepeaterConfigurationOutcome,
    FmRepeaterConfigurationStatus,
    FmRepeaterUnsupportedReason,
)
from rolling_thunder.repeater_active_override_controller import (
    RepeaterActiveOverrideStatus,
)
from rolling_thunder.repeater_configuration import (
    RepeaterConfigurationStatus,
    RepeaterConfigurationStatusKind,
)
from rolling_thunder.repeater_domain import (
    RepeaterChannelType,
    RepeaterIdentity,
    RepeaterLocation,
    RepeaterRecord,
)
from rolling_thunder.repeater_nearby import NearbyRepeaterStateKind
from rolling_thunder.repeater_panel import (
    RepeaterDisplayFilter,
    RepeaterPanelRow,
    RepeaterPanelState,
)
from rolling_thunder.repeater_ui import build_repeater_viewport


def row(
    name: str,
    rx_hz: int,
    distance: float,
    *,
    active: bool,
    selected: bool = False,
) -> RepeaterPanelRow:
    rx = Frequency(hz=rx_hz)
    record = RepeaterRecord(
        identity=RepeaterIdentity(name=name, rx_frequency=rx),
        name=name,
        callsign=name.split()[0],
        channel_type=RepeaterChannelType.ANALOGUE,
        rx_frequency=rx,
        tx_frequency=Frequency(hz=rx_hz - 1_000_000),
        bandwidth_khz=Decimal(25),
        rx_tone_hz=Decimal("131.8"),
        tx_tone_hz=Decimal("131.8"),
        location=RepeaterLocation(latitude=39.5, longitude=-84.0),
        source_active=True,
    )
    return RepeaterPanelRow(
        repeater=record,
        distance_miles=distance,
        effective_active=active,
        selected=selected,
    )


def state(
    *rows: RepeaterPanelRow,
    display_filter: RepeaterDisplayFilter = RepeaterDisplayFilter.ALL,
) -> RepeaterPanelState:
    selected = next((item.stable_key for item in rows if item.selected), None)
    return RepeaterPanelState(
        nearby_kind=NearbyRepeaterStateKind.READY,
        nearby_detail=f"{len(rows)} REPEATERS WITHIN 50 MILES",
        display_filter=display_filter,
        rows=rows,
        selected_stable_key=selected,
    )


def test_viewport_formats_frequency_shift_tones_distance_and_active_state() -> None:
    viewport = build_repeater_viewport(
        state(
            row(
                "KB3AWQ Williamsp",
                53_050_000,
                12.34,
                active=False,
                selected=True,
            )
        )
    )

    card = viewport.cards[0]
    assert card.line1 == "KB3AWQ Williamsp"
    assert card.line2 == "53.050 MHz  SHIFT -1.000"
    assert card.line3 == "TX TONE 131.8  RX TONE 131.8"
    assert card.line4 == "12.3 mi  INACTIVE"
    assert card.selected is True
    assert card.active is False


def test_selected_row_remains_in_bounded_three_card_window() -> None:
    rows = tuple(
        row(
            f"K1AA{index} Test",
            52_000_000 + index * 10_000,
            float(index),
            active=True,
            selected=index == 4,
        )
        for index in range(5)
    )

    viewport = build_repeater_viewport(state(*rows))

    assert len(viewport.cards) == 3
    assert viewport.cards[-1].selected is True
    assert viewport.hidden_above_count == 2
    assert viewport.hidden_below_count == 0


def test_truthful_stale_gps_state_is_presented_without_cards() -> None:
    panel_state = RepeaterPanelState(
        nearby_kind=NearbyRepeaterStateKind.GPS_STALE,
        nearby_detail="GPS STALE — NEARBY REPEATERS UNAVAILABLE",
        display_filter=RepeaterDisplayFilter.ACTIVE_ONLY,
        rows=(),
    )

    viewport = build_repeater_viewport(panel_state)

    assert viewport.has_cards is False
    assert "GPS STALE" in viewport.status_line
    assert viewport.detail_line == "GPS STALE — NEARBY REPEATERS UNAVAILABLE"


def test_normal_footer_assigns_encoder_staging_and_active_toggle_distinctly() -> None:
    panel_state = state(
        row("K1AAA Alpha", 52_010_000, 5.0, active=True, selected=True),
        display_filter=RepeaterDisplayFilter.ACTIVE_ONLY,
    )

    viewport = build_repeater_viewport(panel_state)

    assert viewport.footer_line == (
        "ENCODER PRESS TO TUNE — BTN1 SHOW ALL — BTN2 TOGGLE ACTIVE"
    )


def test_configuration_status_reports_success_failure_and_manual_handoff() -> None:
    panel_state = state(
        row("K1AAA Alpha", 52_010_000, 5.0, active=True, selected=True)
    )
    manual_outcome = FmRepeaterConfigurationOutcome(
        status=FmRepeaterConfigurationStatus.UNSUPPORTED_MANUAL_HANDOFF,
        unsupported_reason=FmRepeaterUnsupportedReason.INDEPENDENT_CTCSS_TONES,
        manual_handoff="CONFIGURE REPEATER MANUALLY",
    )

    configuring = build_repeater_viewport(
        panel_state,
        configuration=RepeaterConfigurationStatus(
            kind=RepeaterConfigurationStatusKind.CONFIGURING
        ),
    )
    configured = build_repeater_viewport(
        panel_state,
        configuration=RepeaterConfigurationStatus(
            kind=RepeaterConfigurationStatusKind.CONFIGURED
        ),
    )
    failed = build_repeater_viewport(
        panel_state,
        configuration=RepeaterConfigurationStatus(
            kind=RepeaterConfigurationStatusKind.FAILED,
            last_error="CAT unavailable",
        ),
    )
    manual = build_repeater_viewport(
        panel_state,
        configuration=RepeaterConfigurationStatus(
            kind=RepeaterConfigurationStatusKind.MANUAL_HANDOFF,
            outcome=manual_outcome,
        ),
    )

    assert configuring.footer_line == "CONFIGURING SELECTED REPEATER…"
    assert configured.footer_line == (
        "REPEATER CONFIGURED — VERIFY ANTENNA/TUNING BEFORE TRANSMIT"
    )
    assert failed.footer_line == "REPEATER CONFIG FAILED — CAT unavailable"
    assert manual.footer_line == "MANUAL HANDOFF — CONFIGURE REPEATER MANUALLY"


def test_persistence_status_is_explicit_in_footer() -> None:
    panel_state = state(
        row("K1AAA Alpha", 52_010_000, 5.0, active=True),
        display_filter=RepeaterDisplayFilter.ACTIVE_ONLY,
    )

    saving = build_repeater_viewport(
        panel_state,
        RepeaterActiveOverrideStatus(saving=True),
    )
    failed = build_repeater_viewport(
        panel_state,
        RepeaterActiveOverrideStatus(last_error="disk unavailable"),
    )

    assert saving.footer_line == "SAVING ACTIVE OVERRIDE…"
    assert failed.footer_line == "ACTIVE SAVE FAILED — disk unavailable"
