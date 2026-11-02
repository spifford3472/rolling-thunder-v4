"""Thread-safe, non-hardware audio ownership gate for speech features."""

from __future__ import annotations

from threading import Lock
from typing import Literal

AudioOwner = Literal["callsign", "tron"]


class TronAudioGate:
    """Prevent concurrent recognizers from accessing the microphone.

    The callsign button must reserve ownership before capture begins. If Tron
    owns the microphone, the coordinator cancels it and promotes callsign only
    after the Tron capture callback exits. This gate does not perform
    cancellation or access audio hardware.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._owner: AudioOwner | None = None
        self._callsign_requested = False

    @property
    def owner(self) -> AudioOwner | None:
        with self._lock:
            return self._owner

    def request_callsign(self) -> bool:
        """Reserve callsign priority; return true if microphone is already free."""
        with self._lock:
            self._callsign_requested = True
            return self._owner is None

    def begin_callsign(self) -> bool:
        """Acquire only after any active Tron worker has actually released audio."""
        with self._lock:
            if self._owner is not None or not self._callsign_requested:
                return False
            self._owner = "callsign"
            self._callsign_requested = False
            return True

    def cancel_callsign_request(self) -> None:
        with self._lock:
            self._callsign_requested = False

    def begin_tron(self) -> bool:
        """Reject Tron during callsign capture or pending callsign priority."""
        with self._lock:
            if self._owner is not None or self._callsign_requested:
                return False
            self._owner = "tron"
            return True

    def release(self, owner: AudioOwner) -> bool:
        """Release only the matching owner's claim."""
        with self._lock:
            if self._owner != owner:
                return False
            self._owner = None
            return True
