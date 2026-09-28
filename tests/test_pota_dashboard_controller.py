"""Tests for POTA dashboard controller filter and provider behavior."""

from datetime import UTC, datetime

from rolling_thunder.domain import Frequency, RadioMode
from rolling_thunder.pota_dashboard_controller import PotaDashboardController
from rolling_thunder.pota_spot_service import PotaSpotServiceState
from rolling_thunder.pota_spot_source import PotaSpotSourceAvailability
from rolling_thunder.pota_spots import AmateurBand, ParkReference, PotaSpot
from rolling_thunder.pota_tune_intent import PotaTuneIntentStatus


class MutableProvider:
    def __init__(self, state: PotaSpotServiceState | None = None) -> None:
        self.latest_pota_spot_state = state


def spot(
    callsign: str,
    reference: str,
    frequency_hz: int,
    mode: RadioMode,
) -> PotaSpot:
    return PotaSpot(
        activator=callsign,
        park=ParkReference(reference=reference),
        frequency=Frequency(hz=frequency_hz),
        mode=mode,
        spotted_at=datetime(2026, 7, 26, 12, 30, tzinfo=UTC),
    )


def available_state() -> PotaSpotServiceState:
    return PotaSpotServiceState(
        availability=PotaSpotSourceAvailability.AVAILABLE,
        spots=(
            spot("KI5VNB", "US-1234", 14_250_000, RadioMode.USB),
            spot("W8ABC", "US-5678", 7_255_000, RadioMode.LSB),
            spot("N0XYZ", "US-9012", 14_074_000, RadioMode.DATA),
        ),
        last_attempt_at=datetime(2026, 7, 26, 12, 30, tzinfo=UTC),
        last_success_at=datetime(2026, 7, 26, 12, 30, tzinfo=UTC),
    )


def test_controller_starts_with_no_filters() -> None:
    controller = PotaDashboardController(MutableProvider(available_state()))

    assert controller.selected_band is None
    assert controller.selected_mode is None
    assert controller.state.visible_spot_count == 3


def test_controller_maps_disabled_provider_state() -> None:
    controller = PotaDashboardController(MutableProvider())

    assert controller.state.status == "DISABLED"
    assert controller.state.rows == ()


def test_select_band_retains_filter_and_returns_filtered_state() -> None:
    controller = PotaDashboardController(MutableProvider(available_state()))

    state = controller.select_band(AmateurBand.BAND_20M)

    assert controller.selected_band is AmateurBand.BAND_20M
    assert state.visible_spot_count == 2
    assert [row.activator for row in state.rows] == ["KI5VNB", "N0XYZ"]


def test_select_mode_combines_with_existing_band_filter() -> None:
    controller = PotaDashboardController(MutableProvider(available_state()))
    controller.select_band(AmateurBand.BAND_20M)

    state = controller.select_mode(RadioMode.USB)

    assert controller.selected_mode is RadioMode.USB
    assert state.visible_spot_count == 1
    assert [row.activator for row in state.rows] == ["KI5VNB"]


def test_select_none_clears_one_filter_without_changing_the_other() -> None:
    controller = PotaDashboardController(MutableProvider(available_state()))
    controller.select_band(AmateurBand.BAND_20M)
    controller.select_mode(RadioMode.USB)

    state = controller.select_mode(None)

    assert controller.selected_band is AmateurBand.BAND_20M
    assert controller.selected_mode is None
    assert state.visible_spot_count == 2


def test_clear_filters_restores_all_rows() -> None:
    controller = PotaDashboardController(MutableProvider(available_state()))
    controller.select_band(AmateurBand.BAND_20M)
    controller.select_mode(RadioMode.USB)

    state = controller.clear_filters()

    assert controller.selected_band is None
    assert controller.selected_mode is None
    assert state.visible_spot_count == 3


def test_state_reads_latest_provider_snapshot_each_time() -> None:
    provider = MutableProvider()
    controller = PotaDashboardController(provider)

    assert controller.state.status == "DISABLED"

    provider.latest_pota_spot_state = available_state()

    assert controller.state.status == "READY"
    assert controller.state.visible_spot_count == 3


def test_unavailable_provider_state_remains_deterministic_with_filters() -> None:
    provider = MutableProvider(
        PotaSpotServiceState(
            availability=PotaSpotSourceAvailability.UNAVAILABLE,
            last_attempt_at=datetime(2026, 7, 26, 12, 30, tzinfo=UTC),
            last_error="request timed out",
        )
    )
    controller = PotaDashboardController(provider)

    state = controller.select_band(AmateurBand.BAND_20M)

    assert state.status == "UNAVAILABLE"
    assert state.error == "request timed out"
    assert state.rows == ()


def test_controller_supplies_clock_for_ranked_dashboard_order() -> None:
    older = PotaSpot(
        activator="K1OLD",
        park=ParkReference(reference="US-1234"),
        frequency=Frequency(hz=14_250_000),
        mode=RadioMode.USB,
        spotted_at=datetime(2026, 7, 26, 12, 0, tzinfo=UTC),
    )
    newer = PotaSpot(
        activator="K1NEW",
        park=ParkReference(reference="US-5678"),
        frequency=Frequency(hz=7_255_000),
        mode=RadioMode.LSB,
        spotted_at=datetime(2026, 7, 26, 12, 25, tzinfo=UTC),
    )
    provider = MutableProvider(
        PotaSpotServiceState(
            availability=PotaSpotSourceAvailability.AVAILABLE,
            spots=(older, newer),
            last_attempt_at=datetime(2026, 7, 26, 12, 30, tzinfo=UTC),
            last_success_at=datetime(2026, 7, 26, 12, 30, tzinfo=UTC),
        )
    )
    controller = PotaDashboardController(
        provider,
        clock=lambda: datetime(2026, 7, 26, 12, 30, tzinfo=UTC),
    )

    assert [row.activator for row in controller.state.rows] == ["K1NEW", "K1OLD"]


def test_next_selects_first_row_then_moves_without_wrapping() -> None:
    controller = PotaDashboardController(
        MutableProvider(available_state()),
        clock=lambda: datetime(2026, 7, 26, 12, 30, tzinfo=UTC),
    )

    first = controller.select_next()
    second = controller.select_next()
    controller.select_next()
    final = controller.select_next()

    assert first.rows[0].is_selected is True
    assert second.rows[1].is_selected is True
    assert final.rows[-1].is_selected is True
    assert controller.selected_index == len(final.rows) - 1


def test_previous_initially_selects_last_row() -> None:
    controller = PotaDashboardController(
        MutableProvider(available_state()),
        clock=lambda: datetime(2026, 7, 26, 12, 30, tzinfo=UTC),
    )

    state = controller.select_previous()

    assert state.rows[-1].is_selected is True


def test_filter_change_clears_selection() -> None:
    controller = PotaDashboardController(
        MutableProvider(available_state()),
        clock=lambda: datetime(2026, 7, 26, 12, 30, tzinfo=UTC),
    )
    controller.select_next()

    state = controller.select_band(AmateurBand.BAND_20M)

    assert controller.selected_index is None
    assert not any(row.is_selected for row in state.rows)


def test_selection_clamps_when_refreshed_rows_shrink() -> None:
    provider = MutableProvider(available_state())
    controller = PotaDashboardController(
        provider,
        clock=lambda: datetime(2026, 7, 26, 12, 30, tzinfo=UTC),
    )
    controller.select_next()
    controller.select_next()
    controller.select_next()

    provider.latest_pota_spot_state = PotaSpotServiceState(
        availability=PotaSpotSourceAvailability.AVAILABLE,
        spots=(spot("KI5VNB", "US-1234", 14_250_000, RadioMode.USB),),
        last_attempt_at=datetime(2026, 7, 26, 12, 30, tzinfo=UTC),
        last_success_at=datetime(2026, 7, 26, 12, 30, tzinfo=UTC),
    )
    state = controller.state

    assert controller.selected_index == 0
    assert state.rows[0].is_selected is True


def test_empty_refresh_clears_selection() -> None:
    provider = MutableProvider(available_state())
    controller = PotaDashboardController(
        provider,
        clock=lambda: datetime(2026, 7, 26, 12, 30, tzinfo=UTC),
    )
    controller.select_next()

    provider.latest_pota_spot_state = PotaSpotServiceState(
        availability=PotaSpotSourceAvailability.AVAILABLE,
        last_attempt_at=datetime(2026, 7, 26, 12, 30, tzinfo=UTC),
        last_success_at=datetime(2026, 7, 26, 12, 30, tzinfo=UTC),
    )
    state = controller.state

    assert controller.selected_index is None
    assert state.rows == ()


def test_request_tune_intent_requires_explicit_selection() -> None:
    controller = PotaDashboardController(
        MutableProvider(available_state()),
        clock=lambda: datetime(2026, 7, 27, 1, 0, tzinfo=UTC),
    )

    assert controller.request_tune_intent() is None
    assert controller.tune_intent is None


def test_request_tune_intent_uses_selected_typed_spot() -> None:
    controller = PotaDashboardController(
        MutableProvider(available_state()),
        clock=lambda: datetime(2026, 7, 27, 1, 0, tzinfo=UTC),
    )
    controller.select_next()

    intent = controller.request_tune_intent()

    assert intent is not None
    assert intent.status is PotaTuneIntentStatus.PENDING_CONFIRMATION
    assert str(intent.activator) == controller.state.rows[0].activator
    assert intent.frequency.hz == 14_250_000
    assert intent.mode is RadioMode.USB
    assert intent.park_reference == "US-1234"


def test_cancel_tune_intent_has_no_radio_side_effect_contract() -> None:
    controller = PotaDashboardController(
        MutableProvider(available_state()),
        clock=lambda: datetime(2026, 7, 27, 1, 0, tzinfo=UTC),
    )
    controller.select_next()
    controller.request_tune_intent()

    cancelled = controller.cancel_tune_intent()

    assert cancelled is not None
    assert cancelled.status is PotaTuneIntentStatus.CANCELLED


def test_selection_change_clears_tune_intent() -> None:
    controller = PotaDashboardController(
        MutableProvider(available_state()),
        clock=lambda: datetime(2026, 7, 27, 1, 0, tzinfo=UTC),
    )
    controller.select_next()
    controller.request_tune_intent()

    controller.select_next()

    assert controller.tune_intent is None


def test_filter_change_clears_tune_intent() -> None:
    controller = PotaDashboardController(
        MutableProvider(available_state()),
        clock=lambda: datetime(2026, 7, 27, 1, 0, tzinfo=UTC),
    )
    controller.select_next()
    controller.request_tune_intent()

    controller.select_band(AmateurBand.BAND_20M)

    assert controller.tune_intent is None


def test_refresh_that_removes_selection_clears_tune_intent() -> None:
    provider = MutableProvider(available_state())
    controller = PotaDashboardController(
        provider,
        clock=lambda: datetime(2026, 7, 27, 1, 0, tzinfo=UTC),
    )
    controller.select_next()
    controller.select_next()
    controller.select_next()
    controller.request_tune_intent()

    provider.latest_pota_spot_state = PotaSpotServiceState(
        availability=PotaSpotSourceAvailability.AVAILABLE,
        spots=(spot("KI5VNB", "US-1234", 14_250_000, RadioMode.USB),),
        last_attempt_at=datetime(2026, 7, 27, 1, 0, tzinfo=UTC),
        last_success_at=datetime(2026, 7, 27, 1, 0, tzinfo=UTC),
    )
    _ = controller.state

    assert controller.tune_intent is None


def test_confirm_tune_intent_requires_pending_intent() -> None:
    controller = PotaDashboardController(
        MutableProvider(available_state()),
        clock=lambda: datetime(2026, 7, 27, 1, 0, tzinfo=UTC),
    )

    assert controller.confirm_tune_intent() is None


def test_confirm_tune_intent_preserves_typed_target() -> None:
    controller = PotaDashboardController(
        MutableProvider(available_state()),
        clock=lambda: datetime(2026, 7, 27, 1, 0, tzinfo=UTC),
    )
    controller.select_next()
    pending = controller.request_tune_intent()

    confirmed = controller.confirm_tune_intent()

    assert pending is not None
    assert confirmed is not None
    assert confirmed.status is PotaTuneIntentStatus.CONFIRMED
    assert confirmed.activator == pending.activator
    assert confirmed.park_reference == pending.park_reference
    assert confirmed.frequency == pending.frequency
    assert confirmed.mode is pending.mode


def test_confirm_tune_intent_rejects_changed_selected_spot() -> None:
    provider = MutableProvider(available_state())
    controller = PotaDashboardController(
        provider,
        clock=lambda: datetime(2026, 7, 27, 1, 0, tzinfo=UTC),
    )
    controller.select_next()
    controller.request_tune_intent()

    provider.latest_pota_spot_state = PotaSpotServiceState(
        availability=PotaSpotSourceAvailability.AVAILABLE,
        spots=(spot("W8NEW", "US-7777", 14_300_000, RadioMode.USB),),
        last_attempt_at=datetime(2026, 7, 27, 1, 0, tzinfo=UTC),
        last_success_at=datetime(2026, 7, 27, 1, 0, tzinfo=UTC),
    )

    assert controller.confirm_tune_intent() is None
    assert controller.tune_intent is None


def test_cancel_is_allowed_after_confirmation() -> None:
    controller = PotaDashboardController(
        MutableProvider(available_state()),
        clock=lambda: datetime(2026, 7, 27, 1, 0, tzinfo=UTC),
    )
    controller.select_next()
    controller.request_tune_intent()
    controller.confirm_tune_intent()

    cancelled = controller.cancel_tune_intent()

    assert cancelled is not None
    assert cancelled.status is PotaTuneIntentStatus.CANCELLED


def test_confirmed_intent_cannot_be_confirmed_again() -> None:
    controller = PotaDashboardController(
        MutableProvider(available_state()),
        clock=lambda: datetime(2026, 7, 27, 1, 0, tzinfo=UTC),
    )
    controller.select_next()
    controller.request_tune_intent()
    confirmed = controller.confirm_tune_intent()

    repeated = controller.confirm_tune_intent()

    assert repeated is confirmed
    assert repeated is not None
    assert repeated.status is PotaTuneIntentStatus.CONFIRMED


def test_visible_spots_exposes_current_filtered_ranked_snapshot() -> None:
    controller = PotaDashboardController(
        MutableProvider(available_state()),
        clock=lambda: datetime(2026, 7, 26, 12, 30, tzinfo=UTC),
    )
    controller.select_band(AmateurBand.BAND_20M)

    visible = controller.visible_spots

    assert [str(item.activator) for item in visible] == [
        "KI5VNB",
        "N0XYZ",
    ]
    assert all(isinstance(item, PotaSpot) for item in visible)
