"""Tests for radio-specific repeater staging invalidation rules."""

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
from rolling_thunder.repeater_panel import RepeaterPanelController


def repeater(name: str, rx_hz: int, *, tone: str = "100.0") -> RepeaterRecord:
    rx = Frequency(hz=rx_hz)
    return RepeaterRecord(
        identity=RepeaterIdentity(name=name, rx_frequency=rx),
        name=name,
        callsign=name.split()[0],
        channel_type=RepeaterChannelType.ANALOGUE,
        rx_frequency=rx,
        tx_frequency=Frequency(hz=rx_hz - 1_000_000),
        bandwidth_khz=Decimal(25),
        rx_tone_hz=Decimal(tone),
        tx_tone_hz=Decimal(tone),
        location=RepeaterLocation(latitude=39.5, longitude=-84.0),
        source_active=True,
    )


def ready(*records: RepeaterRecord) -> NearbyRepeaterState:
    return NearbyRepeaterState(
        kind=NearbyRepeaterStateKind.READY,
        repeaters=tuple(
            NearbyRepeater(record, distance_miles=float(index + 1), effective_active=True)
            for index, record in enumerate(records)
        ),
        detail="READY",
    )


def test_first_radio_stage_has_zero_external_side_effects() -> None:
    alpha = repeater("K8AAA Alpha", 53_050_000)
    current = [ready(alpha)]
    applied: list[tuple[str, bool]] = []
    panel = RepeaterPanelController(
        lambda: current[0],
        apply_override=lambda key, active: applied.append((key, active)),
    )
    panel.select_next()

    state = panel.stage_selected_radio()

    assert state.radio_staged_action is not None
    assert state.radio_staged_action.repeater == alpha
    assert applied == []
    assert state.staged_action is None


def test_rotation_filter_and_radio_loss_invalidate_only_radio_stage() -> None:
    alpha = repeater("K8AAA Alpha", 53_050_000)
    bravo = repeater("K8BBB Bravo", 53_060_000)
    current = [ready(alpha, bravo)]
    panel = RepeaterPanelController(lambda: current[0])
    panel.select_next()
    panel.stage_selected_radio()
    assert panel.radio_staged_action is not None

    panel.select_next()
    assert panel.radio_staged_action is None

    panel.stage_selected_radio()
    panel.toggle_filter()
    assert panel.radio_staged_action is None

    panel.stage_selected_radio()
    panel.invalidate_radio()
    assert panel.radio_staged_action is None


def test_action_critical_source_change_invalidates_without_neighbor_fallback() -> None:
    before = repeater("K8AAA Alpha", 53_050_000, tone="100.0")
    after = repeater("K8AAA Alpha", 53_050_000, tone="123.0")
    current = [ready(before)]
    panel = RepeaterPanelController(lambda: current[0])
    panel.select_next()
    panel.stage_selected_radio()
    assert panel.radio_staged_action is not None

    current[0] = ready(after)

    assert panel.radio_staged_action is None
    assert panel.selected_stable_key == after.stable_key


def test_completed_active_override_invalidates_radio_stage_but_not_active_concern() -> None:
    alpha = repeater("K8AAA Alpha", 53_050_000)
    current = [ready(alpha)]

    def apply_override(_key: str, active: bool) -> None:
        current[0] = NearbyRepeaterState(
            kind=NearbyRepeaterStateKind.READY,
            repeaters=(NearbyRepeater(alpha, distance_miles=1.0, effective_active=active),),
            detail="READY",
        )

    panel = RepeaterPanelController(lambda: current[0], apply_override=apply_override)
    panel.toggle_filter()
    panel.select_next()
    active_action = panel.stage_selected().staged_action
    assert active_action is not None
    panel.cancel_staging()
    panel.stage_selected_radio()
    assert panel.radio_staged_action is not None

    panel.apply_persisted_override(active_action)

    assert panel.radio_staged_action is None
