"""Tests for stable selection and exact receive-action primitives."""

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
from rolling_thunder.spot_selection import SpotSelectionController, StagedSpotAction


def pota_spot(
    callsign: str,
    reference: str,
    frequency_hz: int,
    *,
    mode: RadioMode = RadioMode.USB,
) -> SpotRecord:
    frequency = Frequency(hz=frequency_hz)
    return SpotRecord(
        identity=PotaSpotIdentity(park_reference=reference, frequency=frequency),
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
    state = SpotSelectionController(snapshot()).state
    with pytest.raises(FrozenInstanceError):
        state.selected_identity = DxSpotIdentity(
            callsign="K1ABC",
            frequency=Frequency(hz=14_025_000),
        )


def test_next_and_previous_use_canonical_snapshot_order_without_wrapping() -> None:
    forty = dx_spot("K1ABC", 7_025_000)
    twenty = dx_spot("W8XYZ", 14_025_000)
    controller = SpotSelectionController(snapshot(twenty, forty))

    assert controller.select_next().selected_identity == forty.identity
    assert controller.select_next().selected_identity == twenty.identity
    assert controller.select_next().selected_identity == twenty.identity
    assert controller.select_previous().selected_identity == forty.identity


def test_snapshot_replacement_preserves_still_present_selected_identity() -> None:
    selected = pota_spot("KI5VNB", "US-1234", 14_250_000)
    controller = SpotSelectionController(snapshot(selected))
    controller.select_identity(selected.identity)

    inserted_before = dx_spot("K1ABC", 7_025_000)
    refreshed_selected = pota_spot("W8NEW", "US-1234", 14_250_000)
    state = controller.replace_snapshot(snapshot(refreshed_selected, inserted_before))

    assert state.selected_identity == selected.identity
    assert state.selected_index == 1
    assert state.selected_spot == refreshed_selected


def test_disappearing_selected_identity_clears_without_neighbor_fallback() -> None:
    first = dx_spot("K1ABC", 7_025_000)
    selected = pota_spot("KI5VNB", "US-1234", 14_250_000)
    neighbor = dx_spot("W8XYZ", 18_080_000)
    controller = SpotSelectionController(snapshot(first, selected, neighbor))
    controller.select_identity(selected.identity)

    state = controller.replace_snapshot(snapshot(first, neighbor))

    assert state.selected_identity is None
    assert state.selected_index is None
    assert state.selected_spot is None


def test_selecting_missing_identity_clears_stale_selection() -> None:
    present = dx_spot("K1ABC", 7_025_000)
    missing = dx_spot("W8XYZ", 14_025_000)
    controller = SpotSelectionController(snapshot(present))
    controller.select_identity(present.identity)

    state = controller.select_identity(missing.identity)

    assert state.selected_identity is None


def test_clear_selection_clears_current_identity() -> None:
    selected = dx_spot("K1ABC", 7_025_000)
    controller = SpotSelectionController(snapshot(selected))
    controller.select_identity(selected.identity)

    assert controller.clear_selection().selected_identity is None


def test_receive_action_snapshots_exact_action_critical_values() -> None:
    selected = pota_spot("KI5VNB", "US-1234", 14_250_000, mode=RadioMode.USB)

    action = StagedSpotAction.from_spot(selected)

    assert action.identity == selected.identity
    assert action.callsign == selected.callsign
    assert action.frequency == selected.frequency
    assert action.mode is RadioMode.USB
    assert action.matches(selected) is True


def test_receive_action_detects_action_critical_record_change() -> None:
    selected = pota_spot("KI5VNB", "US-1234", 14_250_000, mode=RadioMode.USB)
    changed = pota_spot("W8NEW", "US-1234", 14_250_000, mode=RadioMode.USB)

    action = StagedSpotAction.from_spot(selected)

    assert action.matches(changed) is False
