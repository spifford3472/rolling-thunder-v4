"""Tests for stable selection and staged-action primitives."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from rolling_thunder.domain import Frequency, RadioMode
from rolling_thunder.spot_domain import (
    DxSpotIdentity,
    PotaSpotIdentity,
    PotaSpotMetadata,
    SpotRecord,
    SpotSnapshot,
)
from rolling_thunder.spot_selection import SpotSelectionController


def pota_spot(
    callsign: str,
    reference: str,
    frequency_hz: int,
    *,
    mode: RadioMode = RadioMode.USB,
) -> SpotRecord:
    frequency = Frequency(hz=frequency_hz)
    return SpotRecord(
        identity=PotaSpotIdentity(
            park_reference=reference,
            frequency=frequency,
        ),
        callsign=callsign,
        frequency=frequency,
        mode=mode,
        display_mode=("SSB" if mode in {RadioMode.LSB, RadioMode.USB} else mode.value),
        spotted_at=datetime(2026, 8, 5, 20, 0, tzinfo=UTC),
        pota=PotaSpotMetadata(park_reference=reference),
    )


def dx_spot(callsign: str, frequency_hz: int) -> SpotRecord:
    frequency = Frequency(hz=frequency_hz)
    return SpotRecord(
        identity=DxSpotIdentity(callsign=callsign, frequency=frequency),
        callsign=callsign,
        frequency=frequency,
        mode=RadioMode.CW,
        display_mode="CW",
        spotted_at=datetime(2026, 8, 5, 20, 0, tzinfo=UTC),
    )


def snapshot(*spots: SpotRecord) -> SpotSnapshot:
    return SpotSnapshot.from_spots(
        generated_at=datetime(2026, 8, 5, 21, 0, tzinfo=UTC),
        spots=spots,
    )


def test_selection_state_is_immutable() -> None:
    controller = SpotSelectionController(snapshot())
    state = controller.state

    with pytest.raises(FrozenInstanceError):
        state.selected_identity = DxSpotIdentity(callsign="K1ABC", frequency=Frequency(hz=14025000))


def test_next_and_previous_use_canonical_snapshot_order_without_wrapping() -> None:
    forty = dx_spot("K1ABC", 7_025_000)
    twenty = dx_spot("W8XYZ", 14_025_000)
    controller = SpotSelectionController(snapshot(twenty, forty))

    first = controller.select_next()
    second = controller.select_next()
    final = controller.select_next()

    assert first.selected_identity == forty.identity
    assert second.selected_identity == twenty.identity
    assert final.selected_identity == twenty.identity

    previous = controller.select_previous()
    assert previous.selected_identity == forty.identity


def test_snapshot_replacement_preserves_selected_and_staged_identity() -> None:
    selected = pota_spot("KI5VNB", "US-1234", 14_250_000)
    controller = SpotSelectionController(snapshot(selected))
    controller.select_identity(selected.identity)
    controller.stage_selected()

    inserted_before = dx_spot("K1ABC", 7_025_000)
    refreshed_selected = pota_spot("KI5VNB", "US-1234", 14_250_000)
    state = controller.replace_snapshot(snapshot(refreshed_selected, inserted_before))

    assert state.selected_identity == selected.identity
    assert state.staged_identity == selected.identity
    assert state.selected_index == 1
    assert state.selected_spot == refreshed_selected
    assert state.staged_spot == refreshed_selected


def test_changed_callsign_clears_staging_but_preserves_selection() -> None:
    original = pota_spot("KI5VNB", "US-1234", 14_250_000)
    refreshed = pota_spot("W8NEW", "US-1234", 14_250_000)
    controller = SpotSelectionController(snapshot(original))
    controller.select_identity(original.identity)
    controller.stage_selected()

    state = controller.replace_snapshot(snapshot(refreshed))

    assert state.selected_identity == original.identity
    assert state.selected_spot == refreshed
    assert state.staged_identity is None
    assert state.staged_action is None
    assert state.staged_spot is None


def test_changed_mode_clears_staging_but_preserves_selection() -> None:
    original = pota_spot("KI5VNB", "US-1234", 14_250_000)
    refreshed = pota_spot(
        "KI5VNB",
        "US-1234",
        14_250_000,
        mode=RadioMode.CW,
    )
    controller = SpotSelectionController(snapshot(original))
    controller.select_identity(original.identity)
    controller.stage_selected()

    state = controller.replace_snapshot(snapshot(refreshed))

    assert state.selected_identity == original.identity
    assert state.selected_spot == refreshed
    assert state.staged_identity is None
    assert state.staged_action is None
    assert state.staged_spot is None


def test_disappearing_selected_identity_clears_without_neighbor_fallback() -> None:
    first = dx_spot("K1ABC", 7_025_000)
    selected = pota_spot("KI5VNB", "US-1234", 14_250_000)
    neighbor = dx_spot("W8XYZ", 18_080_000)
    controller = SpotSelectionController(snapshot(first, selected, neighbor))
    controller.select_identity(selected.identity)
    controller.stage_selected()

    state = controller.replace_snapshot(snapshot(first, neighbor))

    assert state.selected_identity is None
    assert state.selected_index is None
    assert state.selected_spot is None
    assert state.staged_identity is None


def test_selecting_missing_identity_clears_stale_selection() -> None:
    present = dx_spot("K1ABC", 7_025_000)
    missing = dx_spot("W8XYZ", 14_025_000)
    controller = SpotSelectionController(snapshot(present))
    controller.select_identity(present.identity)
    controller.stage_selected()

    state = controller.select_identity(missing.identity)

    assert state.selected_identity is None
    assert state.staged_identity is None


def test_selection_change_clears_staging() -> None:
    first = dx_spot("K1ABC", 7_025_000)
    second = dx_spot("W8XYZ", 14_025_000)
    controller = SpotSelectionController(snapshot(first, second))
    controller.select_identity(first.identity)
    controller.stage_selected()

    state = controller.select_next()

    assert state.selected_identity == second.identity
    assert state.staged_identity is None


def test_unchanged_edge_selection_retains_staging() -> None:
    only = dx_spot("K1ABC", 7_025_000)
    controller = SpotSelectionController(snapshot(only))
    controller.select_next()
    controller.stage_selected()

    state = controller.select_next()

    assert state.selected_identity == only.identity
    assert state.staged_identity == only.identity


def test_stage_requires_current_selection() -> None:
    controller = SpotSelectionController(snapshot())

    state = controller.stage_selected()

    assert state.staged_identity is None
    assert state.staged_spot is None


@pytest.mark.parametrize(
    "clear_method",
    [
        "cancel_staging",
        "invalidate_context",
        "invalidate_radio",
        "record_failure",
    ],
)
def test_required_invalidation_paths_clear_staging(
    clear_method: str,
) -> None:
    selected = dx_spot("K1ABC", 7_025_000)
    controller = SpotSelectionController(snapshot(selected))
    controller.select_identity(selected.identity)
    controller.stage_selected()

    state = getattr(controller, clear_method)()

    assert state.selected_identity == selected.identity
    assert state.staged_identity is None


def test_clear_selection_clears_selection_and_staging() -> None:
    selected = dx_spot("K1ABC", 7_025_000)
    controller = SpotSelectionController(snapshot(selected))
    controller.select_identity(selected.identity)
    controller.stage_selected()

    state = controller.clear_selection()

    assert state.selected_identity is None
    assert state.staged_identity is None
