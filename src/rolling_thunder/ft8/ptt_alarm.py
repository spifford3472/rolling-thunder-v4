"""Thread-safe FT8 uncertain-PTT warning with guarded operator dismissal."""

from __future__ import annotations

from threading import Lock

from rolling_thunder.physical_controls import ControlAction


class FT8PttAlarm:
    """Dismiss warning via voice cancel only; TX inhibition persists."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._active = False
        self._tx_inhibited = False
        self._unlock_progress = 0

    def trigger(self) -> None:
        with self._lock:
            self._active = True
            self._tx_inhibited = True
            self._unlock_progress = 0

    def voice_cancel(self) -> None:
        """Operator acknowledgment stops visual/audible warning, not TX inhibit."""
        with self._lock:
            self._active = False

    def unlock_step(self, action: ControlAction, *, ft8_screen: bool,
                    radio_confirmed_receive: bool,
                    operator_recovery_override: bool = False) -> bool:
        """Clear only on acknowledged FT8 1-3-1 and an explicit recovery choice.

        The operator override is manual authority, not a physical RX sensor.
        Neither path keys the radio or starts an FT8 transmission.
        """
        sequence = (ControlAction.PANEL_PRIMARY, ControlAction.PANEL_TERTIARY,
                    ControlAction.PANEL_PRIMARY)
        with self._lock:
            if not self._tx_inhibited or self._active:
                return False
            if not ft8_screen or not (
                radio_confirmed_receive or operator_recovery_override
            ):
                self._unlock_progress = 0
                return False
            if action not in sequence:
                self._unlock_progress = 0
                return False
            expected = sequence[self._unlock_progress]
            self._unlock_progress = (self._unlock_progress + 1) if action is expected else (
                1 if action is sequence[0] else 0
            )
            if self._unlock_progress == len(sequence):
                self._tx_inhibited = False
                self._unlock_progress = 0
                return True
            return False

    @property
    def active(self) -> bool:
        with self._lock:
            return self._active

    @property
    def audible(self) -> bool:
        return self.active

    @property
    def tx_inhibited(self) -> bool:
        with self._lock:
            return self._tx_inhibited
