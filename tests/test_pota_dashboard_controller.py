"""Tests for POTA dashboard controller filter and provider behavior."""

from datetime import UTC, datetime

from rolling_thunder.domain import Frequency, RadioMode
from rolling_thunder.pota_dashboard_controller import PotaDashboardController
from rolling_thunder.pota_spot_service import PotaSpotServiceState
from rolling_thunder.pota_spot_source import PotaSpotSourceAvailability
from rolling_thunder.pota_spots import AmateurBand, ParkReference, PotaSpot


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
