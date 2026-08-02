from rolling_thunder.domain import Frequency
from rolling_thunder.pota_dashboard_controller import PotaDashboardController
from rolling_thunder.pota_dashboard_filters import PotaDashboardFilterController


class StubProvider:
    latest_pota_spot_state = None


def build_filters() -> PotaDashboardFilterController:
    return PotaDashboardFilterController(PotaDashboardController(StubProvider()))


def test_initial_state_uses_mobile_defaults() -> None:
    filters = build_filters()

    assert filters.state.band_label == "20"
    assert filters.state.mode_label == "SSB"
    assert filters.state.display_line == "POTA    BAND: 20    MODE: SSB"
    assert filters.state.dashboard.status == "DISABLED"


def test_activation_uses_current_supported_radio_band() -> None:
    filters = build_filters()

    state = filters.activate_for_frequency(Frequency(hz=7_200_000))

    assert state.band_label == "40"
    assert state.mode_label == "SSB"


def test_activation_falls_back_to_twenty_meters_for_unsupported_band() -> None:
    filters = build_filters()

    state = filters.activate_for_frequency(Frequency(hz=50_125_000))

    assert state.band_label == "20"


def test_band_cycle_matches_mobile_order_and_wraps() -> None:
    filters = build_filters()
    expected = ("17", "15", "12", "10", "80", "40", "20")

    assert tuple(filters.next_band().band_label for _ in expected) == expected


def test_mode_cycle_matches_operator_order_and_wraps() -> None:
    filters = build_filters()
    expected = ("CW", "FT4", "FT8", "DATA", "ALL", "SSB")

    assert tuple(filters.next_mode().mode_label for _ in expected) == expected


def test_previous_cycles_wrap_in_reverse() -> None:
    filters = build_filters()

    assert filters.previous_band().band_label == "40"
    assert filters.previous_mode().mode_label == "ALL"


def test_reset_defaults_restores_twenty_meter_ssb() -> None:
    filters = build_filters()
    filters.next_band()
    filters.next_mode()

    state = filters.reset_defaults()

    assert state.band_label == "20"
    assert state.mode_label == "SSB"


def test_handle_key_dispatches_retained_development_commands() -> None:
    filters = build_filters()

    assert filters.handle_key("]") is True
    assert filters.state.band_label == "17"
    assert filters.handle_key(".") is True
    assert filters.state.mode_label == "CW"
    assert filters.handle_key("/") is True
    assert filters.state.band_label == "20"
    assert filters.state.mode_label == "SSB"


def test_handle_key_rejects_unrecognized_input_without_change() -> None:
    filters = build_filters()

    assert filters.handle_key("1") is False
    assert filters.state.band_label == "20"
    assert filters.state.mode_label == "SSB"
