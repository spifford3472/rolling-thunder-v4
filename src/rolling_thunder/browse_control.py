"""Background receive-only controls for the free-form Browse page."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from threading import Lock, Thread

from rolling_thunder.domain import (
    Frequency,
    RadioConnectionState,
    RadioMode,
    RadioState,
)
from rolling_thunder.radio import Radio, RadioError

_BROWSE_STEPS_HZ = (100, 500, 1_000)
_BROWSE_MODES = ("CW", "FM", "SSB", "AM")


@dataclass(frozen=True)
class BrowseControlState:
    """Immutable Browse control state consumed by the dashboard."""

    step_hz: int = 100
    busy: bool = False
    last_error: str | None = None

    @property
    def step_label(self) -> str:
        if self.step_hz >= 1_000:
            return f"{self.step_hz // 1_000} kHz"
        return f"{self.step_hz} Hz"


def browse_mode_label(mode: RadioMode | None) -> str:
    """Collapse USB/LSB into the operator-facing SSB label."""
    if mode in {RadioMode.USB, RadioMode.LSB}:
        return "SSB"
    return mode.value if mode is not None else "--"


def browse_ssb_mode(frequency_hz: int) -> RadioMode:
    """Choose the operator-facing SSB sideband for the current frequency."""
    if 5_330_500 <= frequency_hz <= 5_406_400:
        return RadioMode.USB
    return RadioMode.LSB if frequency_hz < 10_000_000 else RadioMode.USB


class BrowseRadioController:
    """Coalesce Browse dial/mode requests onto one background radio worker."""

    def __init__(
        self,
        radio: Radio,
        radio_state: Callable[[], RadioState],
    ) -> None:
        self._radio = radio
        self._radio_state = radio_state
        self._lock = Lock()
        self._state = BrowseControlState()
        self._pending_frequency_hz: int | None = None
        self._pending_mode: RadioMode | None = None
        self._worker_running = False

    @property
    def state(self) -> BrowseControlState:
        with self._lock:
            return self._state

    def cycle_step(self) -> bool:
        """Cycle 100 Hz -> 500 Hz -> 1 kHz -> 100 Hz."""
        with self._lock:
            current_index = _BROWSE_STEPS_HZ.index(self._state.step_hz)
            next_step = _BROWSE_STEPS_HZ[(current_index + 1) % len(_BROWSE_STEPS_HZ)]
            self._state = replace(self._state, step_hz=next_step)
        return True

    def adjust_frequency(self, direction: int) -> bool:
        """Queue one receive-frequency step; negative is down, positive is up."""
        if direction not in {-1, 1}:
            raise ValueError("Browse frequency direction must be -1 or 1.")

        radio_state = self._radio_state()
        if not self._usable(radio_state):
            return False
        current_frequency = radio_state.frequency
        assert current_frequency is not None

        with self._lock:
            base_hz = self._pending_frequency_hz
            if base_hz is None:
                assert radio_state.frequency is not None
                base_hz = radio_state.frequency.hz
            target_hz = base_hz + direction * self._state.step_hz
            if target_hz <= 0:
                return False
            self._pending_frequency_hz = target_hz
            self._state = replace(self._state, busy=True, last_error=None)
            self._ensure_worker_locked()
        return True

    def cycle_mode(self) -> bool:
        """Queue the next CW/FM/SSB/AM receive mode."""
        radio_state = self._radio_state()
        if not self._usable(radio_state):
            return False
        current_frequency = radio_state.frequency
        assert current_frequency is not None

        with self._lock:
            pending = self._pending_mode
            current_label = browse_mode_label(pending or radio_state.mode)
            try:
                current_index = _BROWSE_MODES.index(current_label)
            except ValueError:
                current_index = -1
            next_label = _BROWSE_MODES[(current_index + 1) % len(_BROWSE_MODES)]
            frequency_hz = (
                self._pending_frequency_hz
                if self._pending_frequency_hz is not None
                else current_frequency.hz
            )
            target_mode = {
                "CW": RadioMode.CW,
                "FM": RadioMode.FM,
                "SSB": browse_ssb_mode(frequency_hz),
                "AM": RadioMode.AM,
            }[next_label]
            self._pending_mode = target_mode
            self._state = replace(self._state, busy=True, last_error=None)
            self._ensure_worker_locked()
        return True

    def _ensure_worker_locked(self) -> None:
        if self._worker_running:
            return
        self._worker_running = True
        Thread(
            target=self._worker,
            daemon=True,
            name="rolling-thunder-browse-radio",
        ).start()

    def _worker(self) -> None:
        while True:
            with self._lock:
                frequency_hz = self._pending_frequency_hz
                mode = self._pending_mode
                self._pending_frequency_hz = None
                self._pending_mode = None
                if frequency_hz is None and mode is None:
                    self._worker_running = False
                    self._state = replace(self._state, busy=False)
                    return

            try:
                if frequency_hz is not None:
                    self._radio.set_frequency(Frequency(hz=frequency_hz))
                if mode is not None:
                    self._radio.set_mode(mode)
            except (RadioError, ValueError) as error:
                with self._lock:
                    self._state = replace(self._state, last_error=str(error))

    @staticmethod
    def _usable(state: RadioState) -> bool:
        return (
            state.connection_state is RadioConnectionState.CONNECTED
            and state.frequency is not None
            and state.mode is not None
            and not state.transmitting
        )
