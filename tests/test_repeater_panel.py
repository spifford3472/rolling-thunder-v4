"""Tests for six-meter repeater panel selection, filtering, and staging."""

from decimal import Decimal

from rolling_thunder.domain import Frequency
from rolling_thunder.repeater_domain import (
    RepeaterChannelType,
    RepeaterIdentity,
    RepeaterLocation,
    RepeaterRecord,
)
from rolling_thunder.repeater_nearby import (
    NearbyRepeater,
    NearbyRepeaterState,
    NearbyRepeaterStateKind,
)
from rolling_thunder.repeater_panel import (
    RepeaterDisplayFilter,
    RepeaterPanelController,
)


def repeater(
    name: str,
    rx_hz: int,
    *,
    tx_hz: int | None = None,
    tone: str | None = "100.0",
    source_active: bool = True,
) -> RepeaterRecord:
    rx = Frequency(hz=rx_hz)
    return RepeaterRecord(
        identity=RepeaterIdentity(name=name, rx_frequency=rx),
        name=name,
        callsign=name.split()[0],
        channel_type=RepeaterChannelType.ANALOGUE,
        rx_frequency=rx,
        tx_frequency=Frequency(hz=tx_hz or rx_hz - 1_000_000),
        bandwidth_khz=Decimal(25),
        rx_tone_hz=Decimal(tone) if tone is not None else None,
        tx_tone_hz=Decimal(tone) if tone is not None else None,
        location=RepeaterLocation(latitude=39.5, longitude=-84.0),
        source_active=source_active,
    )


def ready(*items: NearbyRepeater) -> NearbyRepeaterState:
    return NearbyRepeaterState(
        kind=NearbyRepeaterStateKind.READY,
        repeaters=items,
        detail=f"{len(items)} REPEATERS WITHIN 50 MILES",
    )


def item(record: RepeaterRecord, distance: float, *, active: bool = True) -> NearbyRepeater:
    return NearbyRepeater(
        repeater=record,
        distance_miles=distance,
        effective_active=active,
    )


def test_active_only_default_and_all_filter_show_inactive_rows() -> None:
    active = repeater("K1AAA Alpha", 52_010_000)
    inactive = repeater("K1BBB Bravo", 52_020_000)
    current = [ready(item(active, 5.0), item(inactive, 6.0, active=False))]
    controller = RepeaterPanelController(lambda: current[0])

    assert controller.display_filter is RepeaterDisplayFilter.ACTIVE_ONLY
    assert [row.repeater.name for row in controller.state.rows] == ["K1AAA Alpha"]

    state = controller.toggle_filter()

    assert state.display_filter is RepeaterDisplayFilter.ALL
    assert [row.repeater.name for row in state.rows] == ["K1AAA Alpha", "K1BBB Bravo"]
    assert [row.effective_active for row in state.rows] == [True, False]


def test_encoder_selection_preserves_stable_identity_on_refresh_reorder() -> None:
    alpha = repeater("K1AAA Alpha", 52_010_000)
    bravo = repeater("K1BBB Bravo", 52_020_000)
    current = [ready(item(alpha, 5.0), item(bravo, 6.0))]
    controller = RepeaterPanelController(lambda: current[0])

    controller.select_next()
    controller.select_next()
    assert controller.selected_stable_key == bravo.stable_key

    current[0] = ready(item(bravo, 4.0), item(alpha, 7.0))

    assert controller.selected_stable_key == bravo.stable_key
    assert [row.selected for row in controller.state.rows] == [True, False]


def test_removed_selected_identity_clears_without_neighboring_fallback() -> None:
    alpha = repeater("K1AAA Alpha", 52_010_000)
    bravo = repeater("K1BBB Bravo", 52_020_000)
    current = [ready(item(alpha, 5.0), item(bravo, 6.0))]
    controller = RepeaterPanelController(lambda: current[0])
    controller.select_next()
    assert controller.selected_stable_key == alpha.stable_key

    current[0] = ready(item(bravo, 4.0))

    state = controller.state
    assert state.selected_stable_key is None
    assert [row.selected for row in state.rows] == [False]


def test_first_press_stages_exact_toggle_without_applying_override() -> None:
    record = repeater("K1AAA Alpha", 52_010_000)
    current = [ready(item(record, 5.0, active=True))]
    applied: list[tuple[str, bool]] = []
    controller = RepeaterPanelController(
        lambda: current[0],
        apply_override=lambda key, active: applied.append((key, active)),
    )
    controller.select_next()

    state = controller.stage_selected()

    assert state.staged_action is not None
    assert state.staged_action.stable_key == record.stable_key
    assert state.staged_action.effective_active is True
    assert state.staged_action.target_active is False
    assert applied == []


def test_selection_change_filter_change_and_back_cancel_staging() -> None:
    alpha = repeater("K1AAA Alpha", 52_010_000)
    bravo = repeater("K1BBB Bravo", 52_020_000)
    current = [ready(item(alpha, 5.0), item(bravo, 6.0))]
    controller = RepeaterPanelController(lambda: current[0])

    controller.select_next()
    controller.stage_selected()
    assert controller.staged_action is not None

    controller.select_next()
    assert controller.staged_action is None

    controller.stage_selected()
    controller.toggle_filter()
    assert controller.staged_action is None

    controller.stage_selected()
    controller.cancel_staging()
    assert controller.staged_action is None


def test_action_critical_source_mutation_invalidates_stage() -> None:
    before = repeater("K1AAA Alpha", 52_010_000, tone="100.0")
    after = repeater("K1AAA Alpha", 52_010_000, tone="123.0")
    current = [ready(item(before, 5.0))]
    controller = RepeaterPanelController(lambda: current[0])
    controller.select_next()
    controller.stage_selected()
    assert controller.staged_action is not None

    current[0] = ready(item(after, 5.0))

    assert controller.staged_action is None
    assert controller.selected_stable_key == after.stable_key


def test_effective_active_mutation_invalidates_stage() -> None:
    record = repeater("K1AAA Alpha", 52_010_000)
    current = [ready(item(record, 5.0, active=True))]
    controller = RepeaterPanelController(lambda: current[0])
    controller.select_next()
    controller.stage_selected()

    current[0] = ready(item(record, 5.0, active=False))

    assert controller.staged_action is None


def test_missing_or_stale_gps_clears_selection_and_exposes_truthful_state() -> None:
    record = repeater("K1AAA Alpha", 52_010_000)
    current = [ready(item(record, 5.0))]
    controller = RepeaterPanelController(lambda: current[0])
    controller.select_next()
    controller.stage_selected()

    current[0] = NearbyRepeaterState(
        kind=NearbyRepeaterStateKind.GPS_STALE,
        detail="GPS STALE — NEARBY REPEATERS UNAVAILABLE",
    )
    state = controller.state

    assert state.nearby_kind is NearbyRepeaterStateKind.GPS_STALE
    assert state.rows == ()
    assert state.selected_stable_key is None
    assert state.staged_action is None
    assert state.nearby_detail == "GPS STALE — NEARBY REPEATERS UNAVAILABLE"


def test_successful_persist_applies_only_in_memory_override_callback() -> None:
    record = repeater("K1AAA Alpha", 52_010_000)
    current = [ready(item(record, 5.0, active=True))]
    applied: list[tuple[str, bool]] = []

    def apply_override(key: str, active: bool) -> None:
        applied.append((key, active))
        current[0] = ready(item(record, 5.0, active=active))

    controller = RepeaterPanelController(
        lambda: current[0],
        apply_override=apply_override,
    )
    controller.select_next()
    staged = controller.stage_selected().staged_action
    assert staged is not None

    controller.apply_persisted_override(staged)

    assert applied == [(record.stable_key, False)]
    assert controller.staged_action is None


def test_completed_other_override_preserves_newer_unrelated_stage() -> None:
    alpha = repeater("K1AAA Alpha", 52_010_000)
    bravo = repeater("K1BBB Bravo", 52_020_000)
    current = [ready(item(alpha, 5.0), item(bravo, 6.0))]

    def apply_override(key: str, active: bool) -> None:
        assert key == alpha.stable_key
        current[0] = ready(item(alpha, 5.0, active=active), item(bravo, 6.0))

    controller = RepeaterPanelController(
        lambda: current[0],
        apply_override=apply_override,
    )
    controller.toggle_filter()
    controller.select_stable_key(alpha.stable_key)
    completed = controller.stage_selected().staged_action
    assert completed is not None
    controller.cancel_staging()
    controller.select_stable_key(bravo.stable_key)
    newer = controller.stage_selected().staged_action
    assert newer is not None

    controller.apply_persisted_override(completed)

    assert controller.selected_stable_key == bravo.stable_key
    assert controller.staged_action == newer
