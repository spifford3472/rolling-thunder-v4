"""Tests for the typed radio boundary and deterministic mock radio."""

from datetime import UTC, datetime, timedelta

import pytest

from rolling_thunder.domain import (
    Frequency,
    RadioConnectionState,
    RadioMode,
)
from rolling_thunder.mock_radio import MockRadio
from rolling_thunder.radio import (
    BandChangeRequiredError,
    Radio,
    RadioBand,
    RadioConnectionError,
)


class AdvancingClock:
    """Return predictable timestamps one second apart."""

    def __init__(self) -> None:
        self._next = datetime(2026, 7, 25, 4, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        current = self._next
        self._next += timedelta(seconds=1)
        return current


def test_mock_radio_satisfies_runtime_radio_protocol() -> None:
    """Application code should accept the mock through the radio port."""
    radio = MockRadio(clock=AdvancingClock())

    assert isinstance(radio, Radio)


def test_mock_radio_starts_disconnected() -> None:
    """Construction should not claim that physical hardware is connected."""
    radio = MockRadio(clock=AdvancingClock())

    state = radio.get_state()

    assert state.connection_state is RadioConnectionState.DISCONNECTED
    assert state.frequency is None
    assert state.mode is None
    assert state.transmitting is False
    assert state.updated_at == datetime(2026, 7, 25, 4, 0, tzinfo=UTC)


def test_connect_exposes_deterministic_initial_readout() -> None:
    """Connecting should expose the configured frequency and mode."""
    radio = MockRadio(
        clock=AdvancingClock(),
        initial_frequency=Frequency(hz=7_200_000),
        initial_mode=RadioMode.LSB,
    )

    state = radio.connect()

    assert state.connection_state is RadioConnectionState.CONNECTED
    assert state.frequency == Frequency(hz=7_200_000)
    assert state.mode is RadioMode.LSB
    assert state.transmitting is False
    assert state.updated_at == datetime(2026, 7, 25, 4, 0, 1, tzinfo=UTC)
    assert radio.get_state() is state


def test_frequency_and_mode_changes_return_new_immutable_snapshots() -> None:
    """Tuning should update state without mutating earlier snapshots."""
    radio = MockRadio(clock=AdvancingClock())
    connected = radio.connect()

    frequency_changed = radio.set_frequency(Frequency(hz=14_300_000))
    mode_changed = radio.set_mode(RadioMode.LSB)

    assert connected.frequency == Frequency(hz=14_250_000)
    assert connected.mode is RadioMode.USB
    assert frequency_changed.frequency == Frequency(hz=14_300_000)
    assert frequency_changed.mode is RadioMode.USB
    assert mode_changed.frequency == Frequency(hz=14_300_000)
    assert mode_changed.mode is RadioMode.LSB
    assert mode_changed.updated_at == datetime(2026, 7, 25, 4, 0, 3, tzinfo=UTC)


@pytest.mark.parametrize(
    ("band", "frequency_hz"),
    [
        (RadioBand.BAND_40M, 7_200_000),
        (RadioBand.BAND_20M, 14_250_000),
        (RadioBand.BAND_6M, 50_125_000),
    ],
)
def test_select_band_changes_band_without_choosing_final_mode(
    band: RadioBand,
    frequency_hz: int,
) -> None:
    """Band selection should not also impose a final receive mode."""
    radio = MockRadio(clock=AdvancingClock())
    radio.connect()

    state = radio.select_band(band)

    assert state.frequency == Frequency(hz=frequency_hz)
    assert state.mode is RadioMode.USB
    assert state.transmitting is False


def test_mock_rejects_cross_band_frequency_change() -> None:
    radio = MockRadio(clock=AdvancingClock())
    radio.connect()

    with pytest.raises(
        BandChangeRequiredError,
        match="Select 40m before changing frequency from 20m",
    ):
        radio.set_frequency(Frequency(hz=7_255_000))

    assert radio.get_state().frequency == Frequency(hz=14_250_000)


@pytest.mark.parametrize("operation", ["frequency", "mode", "band"])
def test_tuning_operations_require_connection(operation: str) -> None:
    """The mock should fail like hardware when tuning while disconnected."""
    radio = MockRadio(clock=AdvancingClock())

    with pytest.raises(RadioConnectionError, match="requires a connected radio"):
        if operation == "frequency":
            radio.set_frequency(Frequency(hz=14_250_000))
        elif operation == "mode":
            radio.set_mode(RadioMode.USB)
        else:
            radio.select_band(RadioBand.BAND_20M)


def test_disconnect_clears_readout_and_preserves_no_transmit_boundary() -> None:
    """Disconnecting should clear unavailable hardware state."""
    radio = MockRadio(clock=AdvancingClock())
    radio.connect()

    state = radio.disconnect()

    assert state.connection_state is RadioConnectionState.DISCONNECTED
    assert state.frequency is None
    assert state.mode is None
    assert state.transmitting is False


def test_mock_radio_can_simulate_actionable_adapter_error() -> None:
    """Application tests should be able to exercise radio failures."""
    radio = MockRadio(clock=AdvancingClock())
    radio.connect()

    state = radio.simulate_error(" CAT reply was malformed ")

    assert state.connection_state is RadioConnectionState.ERROR
    assert state.frequency is None
    assert state.mode is None
    assert state.last_error == "CAT reply was malformed"
    assert state.transmitting is False

    with pytest.raises(RadioConnectionError):
        radio.set_frequency(Frequency(hz=7_200_000))


def test_reconnect_recovers_from_simulated_error() -> None:
    """A mock error should not permanently poison the adapter."""
    radio = MockRadio(clock=AdvancingClock())
    radio.simulate_error("Disconnected")

    state = radio.connect()

    assert state.connection_state is RadioConnectionState.CONNECTED
    assert state.frequency == Frequency(hz=14_250_000)
    assert state.mode is RadioMode.USB
    assert state.last_error is None


def test_mock_radio_rejects_naive_clock() -> None:
    """Mock timestamps must preserve the domain model's UTC boundary."""

    def naive_clock() -> datetime:
        return datetime(2026, 7, 25, 4, 0)  # noqa: DTZ001

    with pytest.raises(ValueError, match="timezone-aware"):
        MockRadio(clock=naive_clock)


def test_radio_protocol_exposes_no_transmit_or_ptt_operation() -> None:
    """The software boundary must not provide a way to key the radio."""
    radio = MockRadio(clock=AdvancingClock())

    assert not hasattr(radio, "transmit")
    assert not hasattr(radio, "ptt")
    assert not hasattr(radio, "set_ptt")
