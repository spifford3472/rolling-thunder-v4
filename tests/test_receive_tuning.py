"""Tests for the ordered receive-only tuning service."""

from datetime import UTC, datetime

import pytest
from typing_extensions import get_protocol_members

from rolling_thunder.domain import (
    Frequency,
    RadioConnectionState,
    RadioMode,
    RadioState,
)
from rolling_thunder.radio import (
    RadioBand,
    RadioConnectionError,
    RadioError,
)
from rolling_thunder.receive_tuning import (
    ReceiveTuneRadio,
    ReceiveTuningService,
)


def radio_state(
    frequency_hz: int,
    mode: RadioMode = RadioMode.USB,
    *,
    transmitting: bool = False,
) -> RadioState:
    return RadioState(
        connection_state=RadioConnectionState.CONNECTED,
        frequency=Frequency(hz=frequency_hz),
        mode=mode,
        transmitting=transmitting,
        updated_at=datetime(2026, 8, 2, 18, 0, tzinfo=UTC),
    )


class FakeReceiveTuneRadio:
    """Deterministic fake recording every ordered radio operation."""

    def __init__(
        self,
        *,
        initial_frequency_hz: int = 14_250_000,
        initial_mode: RadioMode = RadioMode.USB,
        transmitting: bool = False,
        fail_operation: str | None = None,
    ) -> None:
        self.state = radio_state(
            initial_frequency_hz,
            initial_mode,
            transmitting=transmitting,
        )
        self.fail_operation = fail_operation
        self.calls: list[tuple[str, object | None]] = []

    def get_state(self) -> RadioState:
        self.calls.append(("get_state", None))
        self._raise_if_requested("get_state")
        return self.state

    def select_band(self, band: RadioBand) -> RadioState:
        self.calls.append(("select_band", band))
        self._raise_if_requested("select_band")

        frequencies = {
            RadioBand.BAND_40M: 7_200_000,
            RadioBand.BAND_20M: 14_250_000,
            RadioBand.BAND_6M: 50_125_000,
        }
        self.state = radio_state(
            frequencies[band],
            self.state.mode or RadioMode.USB,
        )
        return self.state

    def set_frequency(self, frequency: Frequency) -> RadioState:
        self.calls.append(("set_frequency", frequency))
        self._raise_if_requested("set_frequency")
        self.state = radio_state(
            frequency.hz,
            self.state.mode or RadioMode.USB,
        )
        return self.state

    def set_mode(self, mode: RadioMode) -> RadioState:
        self.calls.append(("set_mode", mode))
        self._raise_if_requested("set_mode")
        frequency = self.state.frequency
        assert frequency is not None
        self.state = radio_state(frequency.hz, mode)
        return self.state

    def _raise_if_requested(self, operation: str) -> None:
        if self.fail_operation == operation:
            raise RadioError(f"{operation} failed")


def test_receive_tune_boundary_exposes_no_transmit_authority() -> None:
    assert get_protocol_members(ReceiveTuneRadio) == {
        "get_state",
        "select_band",
        "set_frequency",
        "set_mode",
    }


def test_cross_band_tuning_selects_band_before_frequency_and_mode() -> None:
    radio = FakeReceiveTuneRadio()
    service = ReceiveTuningService(radio)

    outcome = service.tune(
        Frequency(hz=7_255_000),
        RadioMode.LSB,
    )

    assert radio.calls == [
        ("get_state", None),
        ("select_band", RadioBand.BAND_40M),
        ("set_frequency", Frequency(hz=7_255_000)),
        ("set_mode", RadioMode.LSB),
    ]
    assert outcome.target_band is RadioBand.BAND_40M
    assert outcome.band_changed is True
    assert outcome.state.frequency == Frequency(hz=7_255_000)
    assert outcome.state.mode is RadioMode.LSB


def test_same_band_tuning_skips_band_selection() -> None:
    radio = FakeReceiveTuneRadio()
    service = ReceiveTuningService(radio)

    outcome = service.tune(
        Frequency(hz=14_300_000),
        RadioMode.USB,
    )

    assert radio.calls == [
        ("get_state", None),
        ("set_frequency", Frequency(hz=14_300_000)),
    ]
    assert outcome.target_band is RadioBand.BAND_20M
    assert outcome.band_changed is False


def test_unknown_current_band_selects_target_band_first() -> None:
    radio = FakeReceiveTuneRadio(initial_frequency_hz=500_000)
    service = ReceiveTuningService(radio)

    service.tune(
        Frequency(hz=7_255_000),
        RadioMode.LSB,
    )

    assert radio.calls[0:2] == [
        ("get_state", None),
        ("select_band", RadioBand.BAND_40M),
    ]


def test_band_failure_prevents_frequency_and_mode_operations() -> None:
    radio = FakeReceiveTuneRadio(fail_operation="select_band")
    service = ReceiveTuningService(radio)

    with pytest.raises(RadioError, match="select_band failed"):
        service.tune(
            Frequency(hz=7_255_000),
            RadioMode.LSB,
        )

    assert radio.calls == [
        ("get_state", None),
        ("select_band", RadioBand.BAND_40M),
    ]


def test_frequency_failure_prevents_mode_operation() -> None:
    radio = FakeReceiveTuneRadio(fail_operation="set_frequency")
    service = ReceiveTuningService(radio)

    with pytest.raises(RadioError, match="set_frequency failed"):
        service.tune(
            Frequency(hz=7_255_000),
            RadioMode.LSB,
        )

    assert radio.calls == [
        ("get_state", None),
        ("select_band", RadioBand.BAND_40M),
        ("set_frequency", Frequency(hz=7_255_000)),
    ]


def test_mode_failure_occurs_only_after_band_and_frequency() -> None:
    radio = FakeReceiveTuneRadio(fail_operation="set_mode")
    service = ReceiveTuningService(radio)

    with pytest.raises(RadioError, match="set_mode failed"):
        service.tune(
            Frequency(hz=7_255_000),
            RadioMode.LSB,
        )

    assert radio.calls == [
        ("get_state", None),
        ("select_band", RadioBand.BAND_40M),
        ("set_frequency", Frequency(hz=7_255_000)),
        ("set_mode", RadioMode.LSB),
    ]


def test_transmitting_radio_rejects_receive_tuning_before_any_change() -> None:
    radio = FakeReceiveTuneRadio(transmitting=True)
    service = ReceiveTuningService(radio)

    with pytest.raises(
        RadioConnectionError,
        match="unavailable while the radio is transmitting",
    ):
        service.tune(
            Frequency(hz=7_255_000),
            RadioMode.LSB,
        )

    assert radio.calls == [("get_state", None)]
