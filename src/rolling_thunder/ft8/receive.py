"""Bounded background FT8 receive pipeline."""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from enum import StrEnum

from rolling_thunder.ft8.activity import FT8CQActivityManager
from rolling_thunder.ft8.audio import FT8AudioInput, FT8AudioInputError
from rolling_thunder.ft8.decoder import FT8Decoder, FT8DecoderError, FT8PcmPeriod
from rolling_thunder.ft8.domain import FT8CQActivity, FT8Period


class FT8ReceiveStatus(StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    DEGRADED = "degraded"


@dataclass(frozen=True, slots=True)
class FT8ReceiveState:
    """Immutable receive-pipeline state for presentation and diagnostics."""

    status: FT8ReceiveStatus = FT8ReceiveStatus.STOPPED
    last_period: FT8Period | None = None
    periods_captured: int = 0
    periods_dropped: int = 0
    decode_count: int = 0
    cq_activity: tuple[FT8CQActivity, ...] = ()
    last_error: str | None = None


class FT8ReceiveService:
    """Capture continuously and decode through a bounded one-period queue."""

    def __init__(
        self,
        audio_input: FT8AudioInput,
        decoder: FT8Decoder,
        activity_manager: FT8CQActivityManager,
        *,
        reconnect_delay_s: float = 2.0,
    ) -> None:
        if reconnect_delay_s <= 0:
            raise ValueError("reconnect_delay_s must be positive")
        self._audio_input = audio_input
        self._decoder = decoder
        self._activity_manager = activity_manager
        self._reconnect_delay_s = reconnect_delay_s
        self._periods: queue.Queue[FT8PcmPeriod] = queue.Queue(maxsize=1)
        self._stop_event = threading.Event()
        self._capture_thread: threading.Thread | None = None
        self._decode_thread: threading.Thread | None = None
        self._state_lock = threading.Lock()
        self._state = FT8ReceiveState()

    @property
    def latest_state(self) -> FT8ReceiveState:
        with self._state_lock:
            return self._state

    @property
    def is_running(self) -> bool:
        return self._capture_thread is not None

    def start(self) -> None:
        if self._capture_thread is not None:
            raise RuntimeError("FT8 receive service is already started")
        self._stop_event.clear()
        self._set_state(status=FT8ReceiveStatus.STARTING, last_error=None)
        self._capture_thread = threading.Thread(
            target=self._capture_loop,
            name="ft8-capture",
            daemon=True,
        )
        self._decode_thread = threading.Thread(
            target=self._decode_loop,
            name="ft8-decode",
            daemon=True,
        )
        self._capture_thread.start()
        self._decode_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._audio_input.stop()
        capture = self._capture_thread
        decode = self._decode_thread
        if capture is not None:
            capture.join(timeout=3)
        if decode is not None:
            decode.join(timeout=3)
        self._capture_thread = None
        self._decode_thread = None
        self._drain_queue()
        self._set_state(status=FT8ReceiveStatus.STOPPED)

    def _capture_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._audio_input.start()
                self._set_state(status=FT8ReceiveStatus.RUNNING, last_error=None)
                while not self._stop_event.is_set():
                    period = self._audio_input.read_period()
                    self._record_capture(period)
                    self._publish_period(period)
            except (FT8AudioInputError, OSError) as exc:
                if self._stop_event.is_set():
                    break
                self._set_state(status=FT8ReceiveStatus.DEGRADED, last_error=str(exc))
                self._audio_input.stop()
                if self._stop_event.wait(self._reconnect_delay_s):
                    break
            finally:
                if self._stop_event.is_set():
                    self._audio_input.stop()

    def _decode_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                period = self._periods.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                decodes = self._decoder.decode(period)
            except (FT8DecoderError, OSError) as exc:
                self._set_state(status=FT8ReceiveStatus.DEGRADED, last_error=str(exc))
                continue

            for decode in decodes:
                self._activity_manager.ingest(decode)
            snapshot = self._activity_manager.snapshot(current_period=period.period)
            with self._state_lock:
                state = self._state
                self._state = FT8ReceiveState(
                    status=state.status,
                    last_period=period.period,
                    periods_captured=state.periods_captured,
                    periods_dropped=state.periods_dropped,
                    decode_count=state.decode_count + len(decodes),
                    cq_activity=snapshot,
                    last_error=state.last_error,
                )

    def _publish_period(self, period: FT8PcmPeriod) -> None:
        try:
            self._periods.put_nowait(period)
            return
        except queue.Full:
            pass

        try:
            self._periods.get_nowait()
        except queue.Empty:
            pass
        self._periods.put_nowait(period)
        with self._state_lock:
            state = self._state
            self._state = FT8ReceiveState(
                status=state.status,
                last_period=state.last_period,
                periods_captured=state.periods_captured,
                periods_dropped=state.periods_dropped + 1,
                decode_count=state.decode_count,
                cq_activity=state.cq_activity,
                last_error="decoder backlog: stale FT8 period dropped",
            )

    def _record_capture(self, period: FT8PcmPeriod) -> None:
        with self._state_lock:
            state = self._state
            self._state = FT8ReceiveState(
                status=state.status,
                last_period=period.period,
                periods_captured=state.periods_captured + 1,
                periods_dropped=state.periods_dropped,
                decode_count=state.decode_count,
                cq_activity=state.cq_activity,
                last_error=state.last_error,
            )

    def _set_state(
        self,
        *,
        status: FT8ReceiveStatus,
        last_error: str | None | object = ...,
    ) -> None:
        with self._state_lock:
            state = self._state
            error = state.last_error if last_error is ... else last_error
            self._state = FT8ReceiveState(
                status=status,
                last_period=state.last_period,
                periods_captured=state.periods_captured,
                periods_dropped=state.periods_dropped,
                decode_count=state.decode_count,
                cq_activity=state.cq_activity,
                last_error=error if isinstance(error, str) or error is None else None,
            )

    def _drain_queue(self) -> None:
        while True:
            try:
                self._periods.get_nowait()
            except queue.Empty:
                return
