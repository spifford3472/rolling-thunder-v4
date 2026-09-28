"""Tests for free-form Browse radio controls."""

from datetime import UTC, datetime
from time import monotonic, sleep

from rolling_thunder.browse_control import (
    BrowseRadioController,
    browse_mode_label,
    browse_ssb_mode,
)
from rolling_thunder.domain import Frequency, RadioMode
from rolling_thunder.mock_radio import MockRadio


def wait_idle(controller: BrowseRadioController) -> None:
    deadline = monotonic() + 2.0
    while controller.state.busy and monotonic() < deadline:
        sleep(0.01)
    assert controller.state.busy is False


def connected_radio(
    *,
    frequency_hz: int = 14_250_000,
    mode: RadioMode = RadioMode.USB,
) -> MockRadio:
    radio = MockRadio(
        clock=lambda: datetime(2026, 9, 28, 20, 0, tzinfo=UTC),
        initial_frequency=Frequency(hz=frequency_hz),
        initial_mode=mode,
    )
    radio.connect()
    return radio


def test_step_cycles_100_500_1000_and_wraps() -> None:
    radio = connected_radio()
    controller = BrowseRadioController(radio, radio_state=radio.get_state)

    assert controller.state.step_hz == 100
    assert controller.cycle_step() is True
    assert controller.state.step_hz == 500
    assert controller.cycle_step() is True
    assert controller.state.step_hz == 1_000
    assert controller.cycle_step() is True
    assert controller.state.step_hz == 100


def test_rotary_left_and_right_adjust_receive_frequency() -> None:
    radio = connected_radio()
    controller = BrowseRadioController(radio, radio_state=radio.get_state)

    assert controller.adjust_frequency(1) is True
    wait_idle(controller)
    assert radio.get_state().frequency == Frequency(hz=14_250_100)

    assert controller.cycle_step() is True
    assert controller.adjust_frequency(-1) is True
    wait_idle(controller)
    assert radio.get_state().frequency == Frequency(hz=14_249_600)


def test_mode_cycle_uses_operator_facing_ssb_choice() -> None:
    radio = connected_radio(mode=RadioMode.FM)
    controller = BrowseRadioController(radio, radio_state=radio.get_state)

    assert controller.cycle_mode() is True
    wait_idle(controller)
    assert radio.get_state().mode is RadioMode.USB
    assert browse_mode_label(radio.get_state().mode) == "SSB"

    assert controller.cycle_mode() is True
    wait_idle(controller)
    assert radio.get_state().mode is RadioMode.AM


def test_ssb_uses_lsb_below_10_mhz_and_usb_at_or_above() -> None:
    assert browse_ssb_mode(7_200_000) is RadioMode.LSB
    assert browse_ssb_mode(14_250_000) is RadioMode.USB



def test_ssb_uses_usb_on_60_meters() -> None:
    assert browse_ssb_mode(5_357_000) is RadioMode.USB
