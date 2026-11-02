"""Cooperative microphone ownership for Tron and physical callsign capture.

Tron workers must honor the stop event and release the device before returning.
This module is independent of ALSA, Vosk and Tk and is safe to unit-test.
"""
from __future__ import annotations

from collections.abc import Callable
from threading import Event, Lock, Thread

from rolling_thunder.tron_audio_gate import TronAudioGate


class TronCaptureCoordinator:
    """Own one cancellable Tron worker; callsign requests have priority."""

    def __init__(self, gate: TronAudioGate | None = None) -> None:
        self.gate = gate or TronAudioGate()
        self._lock = Lock()
        self._worker: Thread | None = None
        self._stop = Event()

    def start_tron(self, capture: Callable[[Event], None]) -> bool:
        """Start one background capture, provided callsign has not reserved audio."""
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return False
            if not self.gate.begin_tron():
                return False
            self._stop = Event()
            stop = self._stop

            def run() -> None:
                try:
                    capture(stop)
                finally:
                    self.gate.release("tron")

            self._worker = Thread(target=run, daemon=True, name="tron-capture")
            self._worker.start()
            return True

    def run_callsign(self, start: Callable[[], bool], *, timeout_s: float = 3.0) -> bool:
        """Stop Tron before calling the existing physical-button capture entry point.

        Fail closed if the Tron worker does not terminate promptly. The caller
        must release the callsign claim when the asynchronous capture finishes.
        """
        if not self.gate.request_callsign():
            with self._lock:
                self._stop.set()
                worker = self._worker
            if worker is not None:
                worker.join(timeout=timeout_s)
                if worker.is_alive():
                    self.gate.cancel_callsign_request()
                    return False
        if not self.gate.begin_callsign():
            self.gate.cancel_callsign_request()
            return False
        try:
            accepted = start()
        except Exception:
            self.gate.release("callsign")
            raise
        if not accepted:
            self.gate.release("callsign")
        return accepted

    def callsign_finished(self) -> None:
        """Release after existing asynchronous callsign capture has stopped."""
        self.gate.release("callsign")

    def stop_tron(self, *, timeout_s: float = 3.0) -> bool:
        """Request cooperative stop and report whether the worker terminated."""
        with self._lock:
            self._stop.set()
            worker = self._worker
        if worker is not None and worker.is_alive():
            worker.join(timeout=timeout_s)
            return not worker.is_alive()
        return True
