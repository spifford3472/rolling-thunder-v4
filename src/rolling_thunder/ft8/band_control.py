"""Background FT8 band cycling through the existing receive-tuning authority."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from threading import Lock, Thread
from typing import Protocol

from rolling_thunder.domain import Frequency, RadioMode, RadioState
from rolling_thunder.ft8.bands import ft8_frequency_for_band, next_automated_ft8_band
from rolling_thunder.radio import RadioBand, RadioError
from rolling_thunder.radio_band import RadioBandResolutionError, resolve_radio_band
from rolling_thunder.receive_tuning import ReceiveTuneOutcome


class FT8ReceiveTuner(Protocol):
    """Narrow receive tuner used by the FT8 band controller."""

    def tune(self, frequency: Frequency, mode: RadioMode) -> ReceiveTuneOutcome:
        """Perform one verified receive-only tune."""
        ...


class FT8BandTuneState(StrEnum):
    IDLE = "idle"
    TUNING = "tuning"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class FT8BandTuneStatus:
    state: FT8BandTuneState = FT8BandTuneState.IDLE
    target_band: RadioBand | None = None
    outcome: ReceiveTuneOutcome | None = None
    error: str | None = None

    @property
    def tuning(self) -> bool:
        return self.state is FT8BandTuneState.TUNING


class FT8BandController:
    """Cycle FT8 receive bands away from the UI thread."""

    def __init__(
        self,
        tuner: FT8ReceiveTuner,
        radio_state: Callable[[], RadioState],
        *,
        ensure_usb_bfo: Callable[[], object] | None = None,
        configure_receive_settings: Callable[[], object] | None = None,
        restore_normal_settings: Callable[[], object] | None = None,
    ) -> None:
        self._tuner = tuner
        self._radio_state = radio_state
        self._ensure_usb_bfo = ensure_usb_bfo
        self._configure_receive_settings = configure_receive_settings
        self._restore_normal_settings = restore_normal_settings
        self._lock = Lock()
        self._operation_lock = Lock()
        self._status = FT8BandTuneStatus()

    @property
    def status(self) -> FT8BandTuneStatus:
        with self._lock:
            return self._status

    def enter_ft8(self) -> bool:
        """Apply verified FT8 receive settings in the background."""
        if self._configure_receive_settings is None:
            return True
        Thread(
            target=self._settings_worker,
            daemon=True,
            name="rolling-thunder-ft8-receive-settings",
        ).start()
        return True

    def exit_ft8(self) -> bool:
        """Restore owner-required normal receive settings in the background."""
        if self._restore_normal_settings is None:
            return True
        Thread(
            target=self._restore_worker,
            daemon=True,
            name="rolling-thunder-ft8-restore-settings",
        ).start()
        return True

    def cycle_band(self) -> bool:
        with self._lock:
            if self._status.tuning:
                return False

        state = self._radio_state()
        current_band: RadioBand | None = None
        if state.frequency is not None:
            try:
                current_band = resolve_radio_band(state.frequency)
            except RadioBandResolutionError:
                current_band = None
        target_band = next_automated_ft8_band(current_band)

        with self._lock:
            if self._status.tuning:
                return False
            self._status = FT8BandTuneStatus(
                state=FT8BandTuneState.TUNING,
                target_band=target_band,
            )

        Thread(
            target=self._worker,
            args=(target_band,),
            daemon=True,
            name="rolling-thunder-ft8-band",
        ).start()
        return True

    def _worker(self, target_band: RadioBand) -> None:
        try:
            with self._operation_lock:
                outcome = self._tuner.tune(
                    ft8_frequency_for_band(target_band),
                    RadioMode.USB,
                )
                if self._ensure_usb_bfo is not None:
                    self._ensure_usb_bfo()
                if self._configure_receive_settings is not None:
                    self._configure_receive_settings()
        except (RadioError, ValueError) as error:
            with self._lock:
                self._status = FT8BandTuneStatus(
                    state=FT8BandTuneState.FAILED,
                    target_band=target_band,
                    error=str(error),
                )
            return

        with self._lock:
            self._status = FT8BandTuneStatus(
                state=FT8BandTuneState.SUCCEEDED,
                target_band=target_band,
                outcome=outcome,
            )


    def _settings_worker(self) -> None:
        callback = self._configure_receive_settings
        if callback is None:
            return
        try:
            with self._operation_lock:
                callback()
        except (RadioError, ValueError):
            return

    def _restore_worker(self) -> None:
        callback = self._restore_normal_settings
        if callback is None:
            return
        try:
            with self._operation_lock:
                callback()
        except (RadioError, ValueError):
            return
