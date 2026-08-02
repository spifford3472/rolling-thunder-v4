"""Ordered receive-only tuning with an enforced band-first workflow."""

from typing import Protocol, runtime_checkable

from rolling_thunder.domain import (
    DomainModel,
    Frequency,
    RadioConnectionState,
    RadioMode,
    RadioState,
)
from rolling_thunder.radio import RadioBand, RadioConnectionError
from rolling_thunder.radio_band import (
    RadioBandResolutionError,
    resolve_radio_band,
)


@runtime_checkable
class ReceiveTuneRadio(Protocol):
    """Minimal receive-only radio boundary required for ordered tuning."""

    def get_state(self) -> RadioState:
        """Return the latest immutable radio state."""
        ...

    def select_band(self, band: RadioBand) -> RadioState:
        """Select and verify one band."""
        ...

    def set_frequency(self, frequency: Frequency) -> RadioState:
        """Set and verify one same-band frequency."""
        ...

    def set_mode(self, mode: RadioMode) -> RadioState:
        """Set and verify one receive mode."""
        ...


class ReceiveTuneOutcome(DomainModel):
    """Verified result from one ordered receive-only tune operation."""

    state: RadioState
    target_band: RadioBand
    band_changed: bool


class ReceiveTuningService:
    """Own the only approved ordering for receive tuning."""

    def __init__(self, radio: ReceiveTuneRadio) -> None:
        self._radio = radio

    def tune(
        self,
        frequency: Frequency,
        mode: RadioMode,
    ) -> ReceiveTuneOutcome:
        """Tune safely using band, frequency, and mode as separate operations."""
        if not isinstance(frequency, Frequency):
            raise TypeError("frequency must be a Frequency")
        if not isinstance(mode, RadioMode):
            raise TypeError("mode must be a RadioMode")

        target_band = resolve_radio_band(frequency)
        state = self._radio.get_state()

        if (
            state.connection_state is not RadioConnectionState.CONNECTED
            or state.frequency is None
        ):
            raise RadioConnectionError(
                "Ordered receive tuning requires a connected radio "
                "with a known current frequency."
            )

        try:
            current_band: RadioBand | None = resolve_radio_band(
                state.frequency
            )
        except RadioBandResolutionError:
            current_band = None

        band_changed = current_band is not target_band

        if band_changed:
            state = self._radio.select_band(target_band)

        state = self._radio.set_frequency(frequency)

        if state.mode is not mode:
            state = self._radio.set_mode(mode)

        return ReceiveTuneOutcome(
            state=state,
            target_band=target_band,
            band_changed=band_changed,
        )
