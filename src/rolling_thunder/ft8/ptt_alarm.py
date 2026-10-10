"""Thread-safe FT8 uncertain-PTT warning with guarded operator dismissal."""

from __future__ import annotations

from threading import Lock


class FT8PttAlarm:
    """Dismiss warning via voice cancel only; TX inhibition persists."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._active = False
        self._tx_inhibited = False

    def trigger(self) -> None:
        with self._lock:
            self._active = True
            self._tx_inhibited = True

    def voice_cancel(self) -> None:
        """Operator acknowledgment stops visual/audible warning, not TX inhibit."""
        with self._lock:
            self._active = False

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
