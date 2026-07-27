from rolling_thunder.domain import RadioMode
from rolling_thunder.pota_dashboard_controller import PotaDashboardController
from rolling_thunder.pota_dashboard_filters import PotaDashboardFilterController
from rolling_thunder.pota_spots import AmateurBand


class StubProvider:
    latest_pota_spot_state = None


def build_filters() -> PotaDashboardFilterController:
    return PotaDashboardFilterController(PotaDashboardController(StubProvider()))


def test_initial_state_shows_all_filters() -> None:
    filters = build_filters()

    assert filters.state.band_label == "ALL"
    assert filters.state.mode_label == "ALL"
    assert filters.state.display_line == "FILTERS — BAND ALL — MODE ALL"
    assert filters.state.dashboard.status == "DISABLED"


def test_next_band_cycles_forward_from_all() -> None:
    filters = build_filters()

    state = filters.next_band()

    assert state.band_label == AmateurBand.BAND_160M.value


def test_previous_band_wraps_from_all() -> None:
    filters = build_filters()

    state = filters.previous_band()

    assert state.band_label == AmateurBand.BAND_6M.value


def test_next_mode_cycles_forward_from_all() -> None:
    filters = build_filters()

    state = filters.next_mode()

    assert state.mode_label == RadioMode.AM.value


def test_previous_mode_wraps_from_all() -> None:
    filters = build_filters()

    state = filters.previous_mode()

    assert state.mode_label == RadioMode.USB.value


def test_clear_resets_band_and_mode() -> None:
    filters = build_filters()
    filters.next_band()
    filters.next_mode()

    state = filters.clear()

    assert state.band_label == "ALL"
    assert state.mode_label == "ALL"


def test_handle_key_dispatches_supported_commands() -> None:
    filters = build_filters()

    assert filters.handle_key("]") is True
    assert filters.state.band_label == AmateurBand.BAND_160M.value
    assert filters.handle_key(".") is True
    assert filters.state.mode_label == RadioMode.AM.value
    assert filters.handle_key("/") is True
    assert filters.state.band_label == "ALL"
    assert filters.state.mode_label == "ALL"


def test_handle_key_rejects_unrecognized_input_without_change() -> None:
    filters = build_filters()

    assert filters.handle_key("1") is False
    assert filters.state.band_label == "ALL"
    assert filters.state.mode_label == "ALL"
