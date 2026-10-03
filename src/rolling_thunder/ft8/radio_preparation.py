"""Fail-closed FT8 radio preparation and normal-operation restore."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from rolling_thunder.domain import Frequency, RadioConnectionState, RadioMode, RadioState
from rolling_thunder.ft8.bands import ft8_frequency_for_band
from rolling_thunder.ft891_cat import Ft891SsbBfo
from rolling_thunder.radio import RadioError
from rolling_thunder.radio_band import RadioBandResolutionError, resolve_radio_band

FT8_OPERATING_POWER_WATTS = 20
FT8_EXIT_POWER_WATTS = 100


class FT8PreparedRadio(Protocol):
    """Narrow radio capability required by FT8 preparation/restore."""

    def refresh_state(self) -> RadioState: ...

    def set_frequency(self, frequency: Frequency) -> RadioState: ...

    def set_mode(self, mode: RadioMode) -> RadioState: ...

    def set_power_watts(self, power_watts: int) -> int: ...

    def set_ssb_bfo(self, value: Ft891SsbBfo) -> Ft891SsbBfo: ...


class FT8ReceiveConfiguredRadio(Protocol):
    """Receive-only FT-891 settings owned by the FT8 page."""

    def set_mode(self, mode: RadioMode) -> RadioState: ...
    def set_ssb_bfo(self, value: Ft891SsbBfo) -> Ft891SsbBfo: ...
    def set_preamp_enabled(self, enabled: bool) -> bool: ...
    def set_narrow_enabled(self, enabled: bool) -> bool: ...
    def set_noise_blanker_enabled(self, enabled: bool) -> bool: ...


def configure_ft8_receive_settings(radio: FT8ReceiveConfiguredRadio) -> None:
    """Force and verify the receive settings required while the FT8 page owns the radio."""
    radio.set_mode(RadioMode.USB)
    radio.set_ssb_bfo(Ft891SsbBfo.USB)
    radio.set_preamp_enabled(True)
    radio.set_narrow_enabled(False)
    radio.set_noise_blanker_enabled(False)


class FT8RadioPreparationError(RadioError):
    """Raised when FT8 cannot safely establish or restore required radio state."""


@dataclass(frozen=True, slots=True)
class FT8PreparedRadioState:
    """Verified radio snapshot immediately before QSO authorization."""

    radio_state: RadioState
    power_watts: int
    ssb_bfo: Ft891SsbBfo


class FT8RadioPreparationService:
    """Apply and verify required FT8 radio settings before transmit authority exists."""

    def __init__(self, radio: FT8PreparedRadio) -> None:
        self._radio = radio

    def prepare_for_qso(self) -> FT8PreparedRadioState:
        """Force 20 W, the current band's FT8 dial frequency, and SSB-BFO USB."""
        initial = self._radio.refresh_state()
        self._require_usable_receive_state(initial)

        assert initial.frequency is not None
        try:
            band = resolve_radio_band(initial.frequency)
        except RadioBandResolutionError as error:
            raise FT8RadioPreparationError(
                "FT8 radio preparation requires a supported amateur band."
            ) from error

        target_frequency = ft8_frequency_for_band(band)

        try:
            power_watts = self._radio.set_power_watts(FT8_OPERATING_POWER_WATTS)
            if initial.frequency != target_frequency:
                self._radio.set_frequency(target_frequency)
            self._radio.set_mode(RadioMode.USB)
            ssb_bfo = self._radio.set_ssb_bfo(Ft891SsbBfo.USB)
            verified = self._radio.refresh_state()
        except (RadioError, ValueError) as error:
            raise FT8RadioPreparationError(
                f"FT8 radio preparation failed: {error}"
            ) from error

        self._require_usable_receive_state(verified)
        if verified.frequency != target_frequency:
            actual_hz = None if verified.frequency is None else verified.frequency.hz
            raise FT8RadioPreparationError(
                "FT8 radio preparation frequency verification failed: "
                f"expected {target_frequency.hz} Hz, got {actual_hz}."
            )
        if verified.mode is not RadioMode.USB:
            actual_mode = None if verified.mode is None else verified.mode.value
            raise FT8RadioPreparationError(
                "FT8 radio preparation mode verification failed: "
                f"expected USB, got {actual_mode}."
            )
        if power_watts != FT8_OPERATING_POWER_WATTS:
            raise FT8RadioPreparationError(
                "FT8 radio preparation power verification failed: "
                f"expected {FT8_OPERATING_POWER_WATTS} W, got {power_watts} W."
            )
        if ssb_bfo is not Ft891SsbBfo.USB:
            raise FT8RadioPreparationError(
                "FT8 radio preparation SSB-BFO verification failed: expected USB."
            )

        return FT8PreparedRadioState(
            radio_state=verified,
            power_watts=power_watts,
            ssb_bfo=ssb_bfo,
        )

    def restore_after_ft8(self) -> None:
        """Force the owner-required 100 W / SSB-BFO AUTO normal configuration."""
        errors: list[str] = []
        try:
            verified_power = self._radio.set_power_watts(FT8_EXIT_POWER_WATTS)
            if verified_power != FT8_EXIT_POWER_WATTS:
                errors.append(
                    "power verification failed: "
                    f"expected {FT8_EXIT_POWER_WATTS} W, got {verified_power} W"
                )
        except (RadioError, ValueError) as error:
            errors.append(f"power restore failed: {error}")

        try:
            verified_bfo = self._radio.set_ssb_bfo(Ft891SsbBfo.AUTO)
            if verified_bfo is not Ft891SsbBfo.AUTO:
                errors.append(
                    "SSB-BFO verification failed: expected AUTO, "
                    f"got {verified_bfo.value.upper()}"
                )
        except (RadioError, ValueError) as error:
            errors.append(f"SSB-BFO restore failed: {error}")

        if errors:
            raise FT8RadioPreparationError(
                "FT8 radio restore failed: " + "; ".join(errors)
            )

    @staticmethod
    def _require_usable_receive_state(state: RadioState) -> None:
        if state.connection_state is not RadioConnectionState.CONNECTED:
            raise FT8RadioPreparationError(
                "FT8 radio preparation requires a connected radio."
            )
        if state.transmitting:
            raise FT8RadioPreparationError(
                "FT8 radio preparation requires the radio to be in receive."
            )
        if state.frequency is None or state.mode is None:
            raise FT8RadioPreparationError(
                "FT8 radio preparation requires known frequency and mode."
            )
