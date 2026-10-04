"""Tests for fail-closed FT8 radio preparation and restore."""

from datetime import UTC, datetime

import pytest

from rolling_thunder.domain import Frequency, RadioConnectionState, RadioMode, RadioState
from rolling_thunder.ft8.radio_preparation import (
    FT8_EXIT_POWER_WATTS,
    FT8_OPERATING_POWER_WATTS,
    FT8RadioPreparationError,
    FT8RadioPreparationService,
    configure_ft8_receive_settings,
)
from rolling_thunder.ft891_cat import Ft891SsbBfo, Ft891SsbMicSelect
from rolling_thunder.radio import RadioConnectionError


def _state(
    *,
    frequency_hz: int = 14_250_000,
    connected: bool = True,
    transmitting: bool = False,
) -> RadioState:
    return RadioState(
        connection_state=(
            RadioConnectionState.CONNECTED if connected else RadioConnectionState.DISCONNECTED
        ),
        frequency=Frequency(hz=frequency_hz) if connected else None,
        mode=RadioMode.DATA if connected else None,
        transmitting=transmitting,
        updated_at=datetime(2026, 10, 2, 20, 0, tzinfo=UTC),
    )


class FakePreparedRadio:
    def __init__(self) -> None:
        self.state = _state()
        self.power_watts = 100
        self.ssb_bfo = Ft891SsbBfo.AUTO
        self.ssb_mic_select = Ft891SsbMicSelect.MIC
        self.fail_mic = False
        self.calls: list[str] = []
        self.fail_power: Exception | None = None
        self.fail_frequency: Exception | None = None
        self.fail_bfo: Exception | None = None

    def refresh_state(self) -> RadioState:
        self.calls.append("refresh")
        return self.state

    def set_frequency(self, frequency: Frequency) -> RadioState:
        self.calls.append(f"frequency:{frequency.hz}")
        if self.fail_frequency is not None:
            raise self.fail_frequency
        self.state = RadioState(
            connection_state=RadioConnectionState.CONNECTED,
            frequency=frequency,
            mode=RadioMode.DATA,
            transmitting=False,
            updated_at=self.state.updated_at,
        )
        return self.state

    def set_mode(self, mode: RadioMode) -> RadioState:
        self.calls.append(f"mode:{mode.value}")
        self.state = RadioState(
            connection_state=self.state.connection_state,
            frequency=self.state.frequency,
            mode=mode,
            transmitting=False,
            updated_at=self.state.updated_at,
        )
        return self.state

    def set_power_watts(self, power_watts: int) -> int:
        self.calls.append(f"power:{power_watts}")
        if self.fail_power is not None:
            raise self.fail_power
        self.power_watts = power_watts
        return self.power_watts

    def set_ssb_mic_select(self, value: Ft891SsbMicSelect) -> Ft891SsbMicSelect:
        self.calls.append(f"mic:{value.value}")
        if getattr(self, "fail_mic", False) and value is Ft891SsbMicSelect.REAR:
            raise FT8RadioPreparationError("REAR unavailable")
        self.ssb_mic_select = value
        return value

    def set_ssb_bfo(self, value: Ft891SsbBfo) -> Ft891SsbBfo:
        self.calls.append(f"bfo:{value.value}")
        if self.fail_bfo is not None:
            raise self.fail_bfo
        self.ssb_bfo = value
        return self.ssb_bfo


class FakeReceiveConfiguredRadio:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def set_mode(self, mode: RadioMode) -> RadioState:
        self.calls.append(f"mode:{mode.value}")
        return _state()

    def set_ssb_mic_select(self, value: Ft891SsbMicSelect) -> Ft891SsbMicSelect:
        self.calls.append(f"mic:{value.value}")
        if getattr(self, "fail_mic", False) and value is Ft891SsbMicSelect.REAR:
            raise FT8RadioPreparationError("REAR unavailable")
        self.ssb_mic_select = value
        return value

    def set_ssb_bfo(self, value: Ft891SsbBfo) -> Ft891SsbBfo:
        self.calls.append(f"bfo:{value.value}")
        return value

    def set_preamp_enabled(self, enabled: bool) -> bool:
        self.calls.append(f"preamp:{enabled}")
        return enabled

    def set_narrow_enabled(self, enabled: bool) -> bool:
        self.calls.append(f"narrow:{enabled}")
        return enabled

    def set_noise_blanker_enabled(self, enabled: bool) -> bool:
        self.calls.append(f"nb:{enabled}")
        return enabled


def test_ft8_receive_setup_forces_usb_and_receiver_defaults() -> None:
    radio = FakeReceiveConfiguredRadio()

    configure_ft8_receive_settings(radio)

    assert radio.calls == [
        "mode:USB",
        "bfo:usb",
        "mic:rear",
        "preamp:True",
        "narrow:False",
        "nb:False",
    ]


def test_prepare_for_qso_forces_20w_frequency_and_usb() -> None:
    radio = FakePreparedRadio()
    service = FT8RadioPreparationService(radio)

    prepared = service.prepare_for_qso()

    assert prepared.power_watts == FT8_OPERATING_POWER_WATTS
    assert prepared.ssb_bfo is Ft891SsbBfo.USB
    assert prepared.radio_state.frequency == Frequency(hz=14_074_000)
    assert radio.calls == [
        "refresh",
        "power:20",
        "frequency:14074000",
        "mode:USB",
        "bfo:usb",
        "mic:rear",
        "refresh",
    ]


def test_prepare_always_sets_20w_even_when_frequency_is_already_correct() -> None:
    radio = FakePreparedRadio()
    radio.state = _state(frequency_hz=14_074_000)

    FT8RadioPreparationService(radio).prepare_for_qso()

    assert "power:20" in radio.calls
    assert "frequency:14074000" not in radio.calls
    assert "bfo:usb" in radio.calls


@pytest.mark.parametrize(
    ("attribute", "message"),
    [
        ("fail_power", "power unavailable"),
        ("fail_frequency", "frequency unavailable"),
        ("fail_bfo", "BFO unavailable"),
    ],
)
def test_prepare_failure_is_fail_closed_before_any_qso_authorization(
    attribute: str,
    message: str,
) -> None:
    radio = FakePreparedRadio()
    setattr(radio, attribute, RadioConnectionError(message))

    with pytest.raises(FT8RadioPreparationError, match=message):
        FT8RadioPreparationService(radio).prepare_for_qso()


def test_prepare_refuses_transmitting_radio_before_changes() -> None:
    radio = FakePreparedRadio()
    radio.state = _state(transmitting=True)

    with pytest.raises(FT8RadioPreparationError, match="in receive"):
        FT8RadioPreparationService(radio).prepare_for_qso()

    assert radio.calls == ["refresh"]


def test_restore_forces_100w_and_auto() -> None:
    radio = FakePreparedRadio()
    radio.power_watts = 20
    radio.ssb_bfo = Ft891SsbBfo.USB

    FT8RadioPreparationService(radio).restore_after_ft8()

    assert radio.power_watts == FT8_EXIT_POWER_WATTS
    assert radio.ssb_bfo is Ft891SsbBfo.AUTO
    assert radio.calls == ["power:100", "bfo:auto", "mic:mic"]


def test_restore_attempts_bfo_even_when_power_restore_fails() -> None:
    radio = FakePreparedRadio()
    radio.fail_power = RadioConnectionError("power write failed")

    with pytest.raises(FT8RadioPreparationError, match="power write failed"):
        FT8RadioPreparationService(radio).restore_after_ft8()

    assert radio.calls == ["power:100", "bfo:auto", "mic:mic"]
    assert radio.ssb_bfo is Ft891SsbBfo.AUTO


def test_restore_reports_both_failures() -> None:
    radio = FakePreparedRadio()
    radio.fail_power = RadioConnectionError("power write failed")
    radio.fail_bfo = RadioConnectionError("BFO write failed")

    with pytest.raises(FT8RadioPreparationError) as raised:
        FT8RadioPreparationService(radio).restore_after_ft8()

    assert "power write failed" in str(raised.value)
    assert "BFO write failed" in str(raised.value)


def test_repeated_entry_normalizes_mic_to_rear() -> None:
    radio = FakeReceiveConfiguredRadio()
    configure_ft8_receive_settings(radio)
    configure_ft8_receive_settings(radio)
    assert radio.ssb_mic_select is Ft891SsbMicSelect.REAR
    assert radio.calls.count("mic:rear") == 2


def test_prepare_rejects_mic_failure() -> None:
    radio = FakePreparedRadio()
    radio.fail_mic = True
    with pytest.raises(FT8RadioPreparationError, match="REAR unavailable"):
        FT8RadioPreparationService(radio).prepare_for_qso()


def test_prepare_rejects_wrong_mic_readback() -> None:
    class WrongReadback(FakePreparedRadio):
        def set_ssb_mic_select(self, value: Ft891SsbMicSelect) -> Ft891SsbMicSelect:
            return Ft891SsbMicSelect.MIC

    with pytest.raises(FT8RadioPreparationError, match="expected REAR"):
        FT8RadioPreparationService(WrongReadback()).prepare_for_qso()


def test_normal_receive_restore_attempts_mic_even_with_bfo_failure() -> None:
    from rolling_thunder.ft8.radio_preparation import restore_ft8_normal_receive_settings

    class FailedBfo(FakeReceiveConfiguredRadio):
        def set_ssb_bfo(self, value: Ft891SsbBfo) -> Ft891SsbBfo:
            raise RadioConnectionError("BFO failed")

    radio = FailedBfo()
    with pytest.raises(FT8RadioPreparationError, match="BFO failed"):
        restore_ft8_normal_receive_settings(radio)
    assert radio.ssb_mic_select is Ft891SsbMicSelect.MIC
