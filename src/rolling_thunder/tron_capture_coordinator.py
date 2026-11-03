"""Nonblocking exclusive microphone ownership with physical callsign priority."""

from __future__ import annotations

import logging
from collections.abc import Callable
from threading import Event, Lock, Thread

from rolling_thunder.tron_audio_gate import TronAudioGate

_LOGGER = logging.getLogger(__name__)
AudioCapture = Callable[[Event], None]
CallsignStart = Callable[[], bool]


class TronCaptureCoordinator:
    """Coordinate one Tron worker and one callsign capture without UI-thread joins."""

    def __init__(
        self,
        gate: TronAudioGate | None = None,
        *,
        on_callsign_finished: Callable[[], None] | None = None,
    ) -> None:
        self.gate = gate or TronAudioGate()
        self._lock = Lock()
        self._worker: Thread | None = None
        self._stop = Event()
        self._callsign_start: CallsignStart | None = None
        self._callsign_active = False
        self._shutdown = False
        self._on_callsign_finished = on_callsign_finished

    def start_tron(self, capture: AudioCapture) -> bool:
        """Start one background listener unless callsign has reserved the device."""
        with self._lock:
            if self._shutdown or (self._worker is not None and self._worker.is_alive()):
                return False
            if not self.gate.begin_tron():
                return False
            stop = Event()
            self._stop = stop
            worker = Thread(
                target=self._run_tron,
                args=(capture, stop),
                daemon=True,
                name="tron-microphone",
            )
            self._worker = worker
            try:
                worker.start()
            except RuntimeError:
                self._worker = None
                self.gate.release("tron")
                return False
        return True

    def request_callsign(self, start: CallsignStart) -> bool:
        """Reserve callsign priority immediately and start capture after Tron exits.

        This method never joins the Tron worker. A pending callsign owns the
        reservation until its existing asynchronous capture finishes.
        """
        start_now: CallsignStart | None = None
        with self._lock:
            if self._shutdown or self._callsign_active or self._callsign_start is not None:
                return False
            if self.gate.owner == "callsign":
                return False
            ready = self.gate.request_callsign()
            self._callsign_start = start
            if ready:
                if self.gate.begin_callsign():
                    self._callsign_start = None
                    self._callsign_active = True
                    start_now = start
                else:
                    self.gate.cancel_callsign_request()
                    self._callsign_start = None
                    return False
            else:
                self._stop.set()
        if start_now is not None:
            return self._start_callsign(start_now)
        return True

    def callsign_finished(self) -> None:
        """Release priority after the recognizer has released its audio process."""
        callback: Callable[[], None] | None = None
        with self._lock:
            self.gate.release("callsign")
            self._callsign_active = False
            if not self._shutdown:
                callback = self._on_callsign_finished
        if callback is not None:
            try:
                callback()
            except Exception:
                _LOGGER.exception("Tron resume after callsign capture failed")

    @property
    def callsign_waiting_for_tron(self) -> bool:
        """Report a reserved callsign waiting for the active Tron worker."""
        with self._lock:
            return self._callsign_start is not None and self._worker is not None

    def request_stop_tron(self) -> None:
        """Signal listener cancellation without waiting for its worker."""
        with self._lock:
            self._stop.set()

    def stop_tron(self, *, timeout_s: float = 3.0) -> bool:
        """Request listener cancellation and join only from a non-UI caller."""
        self.request_stop_tron()
        with self._lock:
            worker = self._worker
        if worker is not None and worker.is_alive():
            worker.join(timeout=max(0.0, timeout_s))
            return not worker.is_alive()
        return True

    def shutdown(self, *, timeout_s: float = 3.0) -> bool:
        """Prevent restarts, cancel Tron, and join it on the caller's thread."""
        with self._lock:
            self._shutdown = True
            self._callsign_start = None
            self.gate.cancel_callsign_request()
            self._stop.set()
            worker = self._worker
        if worker is not None and worker.is_alive():
            worker.join(timeout=max(0.0, timeout_s))
            return not worker.is_alive()
        return True

    def _run_tron(self, capture: AudioCapture, stop: Event) -> None:
        try:
            capture(stop)
        except Exception:
            _LOGGER.exception("Tron microphone worker failed")
        finally:
            self.gate.release("tron")
            start: CallsignStart | None = None
            with self._lock:
                self._worker = None
                if not self._shutdown and self._callsign_start is not None:
                    if self.gate.begin_callsign():
                        start = self._callsign_start
                        self._callsign_start = None
                        self._callsign_active = True
                    else:
                        self._callsign_start = None
                        self.gate.cancel_callsign_request()
            if start is not None:
                self._start_callsign(start)

    def _start_callsign(self, start: CallsignStart) -> bool:
        try:
            accepted = start()
        except Exception:
            _LOGGER.exception("Priority callsign capture could not start")
            accepted = False
        if not accepted:
            callback: Callable[[], None] | None = None
            with self._lock:
                self.gate.release("callsign")
                self._callsign_active = False
                if not self._shutdown:
                    callback = self._on_callsign_finished
            if callback is not None:
                try:
                    callback()
                except Exception:
                    _LOGGER.exception("Tron resume after rejected callsign capture failed")
        return accepted
