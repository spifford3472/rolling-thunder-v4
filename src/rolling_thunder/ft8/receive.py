"""Bounded background FT8 receive pipeline."""

from __future__ import annotations

import json
import os
import queue
import threading
import time
import wave
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from rolling_thunder.ft8.activity import FT8CQActivityManager
from rolling_thunder.ft8.audio import FT8AudioInput, FT8AudioInputError
from rolling_thunder.ft8.decoder import (
    FT8Decoder,
    FT8DecoderDiagnostics,
    FT8DecoderError,
    FT8DecoderResult,
    FT8PcmPeriod,
)
from rolling_thunder.ft8.diagnostics import (
    FT8AudioDiagnostics,
    FT8ClockDiagnostics,
    FT8ClockQuality,
    FT8DiagnosticSessionState,
    FT8MorningDiagnosticSession,
    NTPClockStatus,
    analyze_ft8_pcm,
    assess_ft8_clock,
    diagnostic_json_value,
)
from rolling_thunder.ft8.domain import (
    FT8CQActivity,
    FT8Decode,
    FT8MessageKind,
    FT8Period,
)
from rolling_thunder.ft8.timing import FT8Clock, SystemFT8Clock
from rolling_thunder.gps import GPSUTCObservation


class FT8ReceiveStatus(StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    DEGRADED = "degraded"


class FT8ReceiveObserver(Protocol):
    """Optional normalized decode/error sink used by an active QSO coordinator."""

    def on_decodes(self, decodes: tuple[FT8Decode, ...]) -> None:
        """Observe one decoder result without affecting CQ ingestion."""
        ...

    def on_receive_error(self, detail: str) -> None:
        """Observe a receive/decoder failure."""
        ...


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
    audio_device: str | None = None
    capture_restarts: int = 0
    capture_errors: int = 0
    last_audio: FT8AudioDiagnostics | None = None
    last_clock: FT8ClockDiagnostics | None = None
    last_decoder: FT8DecoderDiagnostics | None = None
    last_comparison_decoder: FT8DecoderDiagnostics | None = None
    decoder_runs: int = 0
    raw_decoder_lines: int = 0
    malformed_decoder_lines: int = 0
    cq_decode_count: int = 0
    saved_periods: int = 0
    diagnostic_session: FT8DiagnosticSessionState | None = None
    last_diagnostic_error: str | None = None


class BoundedFT8PeriodRecorder:
    """Save an explicitly configured maximum of exact captured WAV periods."""

    def __init__(self, directory: Path, *, maximum_periods: int) -> None:
        if maximum_periods < 1 or maximum_periods > 3:
            raise ValueError("maximum_periods must be between 1 and 3")
        self._directory = directory
        self._maximum_periods = maximum_periods
        self._saved = 0

    @property
    def saved(self) -> int:
        return self._saved

    def save(self, pcm: FT8PcmPeriod) -> Path | None:
        if self._saved >= self._maximum_periods:
            return None
        self._directory.mkdir(parents=True, exist_ok=True)
        slot = self._saved + 1
        path = self._directory / f"ft8-period-{slot:02d}.wav"
        temporary = path.with_suffix(".wav.tmp")
        with wave.open(str(temporary), "wb") as target:
            target.setnchannels(1)
            target.setsampwidth(2)
            target.setframerate(pcm.sample_rate_hz)
            target.writeframes(pcm.pcm_s16le)
        os.replace(temporary, path)
        self._saved += 1
        return path


class FT8ReceiveService:
    """Capture continuously and decode through a bounded one-period queue."""

    def __init__(
        self,
        audio_input: FT8AudioInput,
        decoder: FT8Decoder,
        activity_manager: FT8CQActivityManager,
        *,
        reconnect_delay_s: float = 2.0,
        observer: FT8ReceiveObserver | None = None,
        clock: FT8Clock | None = None,
        gps_utc: Callable[[], GPSUTCObservation | None] | None = None,
        ntp_status: Callable[[], NTPClockStatus] | None = None,
        recorder: BoundedFT8PeriodRecorder | None = None,
        diagnostic_session: FT8MorningDiagnosticSession | None = None,
        diagnostic_snapshot_path: Path | None = None,
    ) -> None:
        if reconnect_delay_s <= 0:
            raise ValueError("reconnect_delay_s must be positive")
        self._audio_input = audio_input
        self._decoder = decoder
        self._activity_manager = activity_manager
        self._reconnect_delay_s = reconnect_delay_s
        self._observer = observer
        self._clock = clock or SystemFT8Clock()
        self._gps_utc = gps_utc
        self._ntp_status = ntp_status
        self._recorder = recorder
        self._diagnostic_session = diagnostic_session
        self._diagnostic_snapshot_path = diagnostic_snapshot_path
        self._observer_lock = threading.Lock()
        self._snapshot_lock = threading.Lock()
        self._periods: queue.Queue[FT8PcmPeriod] = queue.Queue(maxsize=1)
        self._stop_event = threading.Event()
        self._capture_thread: threading.Thread | None = None
        self._decode_thread: threading.Thread | None = None
        self._state_lock = threading.Lock()
        self._capture_healthy = False
        device = getattr(audio_input, "device", None)
        self._state = FT8ReceiveState(
            audio_device=device if isinstance(device, str) else None,
            diagnostic_session=(
                None
                if diagnostic_session is None
                else diagnostic_session.latest_state
            ),
        )

    @property
    def latest_state(self) -> FT8ReceiveState:
        with self._state_lock:
            return self._state

    @property
    def is_running(self) -> bool:
        return self._capture_thread is not None

    def set_observer(self, observer: FT8ReceiveObserver | None) -> None:
        """Attach or detach the single active-QSO decode observer."""
        with self._observer_lock:
            self._observer = observer

    def clear_cq_activity(self) -> None:
        """Drop accumulated CQ rows when the active FT8 receive band changes."""
        self._activity_manager.clear()
        with self._state_lock:
            state = self._state
            self._state = replace(state, cq_activity=())

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
        if self._diagnostic_session is not None:
            session_state = self._diagnostic_session.latest_state
            with self._state_lock:
                self._state = replace(
                    self._state,
                    diagnostic_session=session_state,
                )
        self._write_diagnostic_snapshot()

    def _capture_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._audio_input.start()
                with self._state_lock:
                    self._capture_healthy = True
                self._set_state(status=FT8ReceiveStatus.RUNNING, last_error=None)
                while not self._stop_event.is_set():
                    period = self._audio_input.read_period()
                    self._record_capture(period)
                    self._publish_period(period)
            except (FT8AudioInputError, OSError) as exc:
                with self._state_lock:
                    self._capture_healthy = False
                if self._stop_event.is_set():
                    break
                detail = str(exc)
                self._set_state(status=FT8ReceiveStatus.DEGRADED, last_error=detail)
                with self._state_lock:
                    self._state = replace(
                        self._state,
                        capture_errors=self._state.capture_errors + 1,
                        capture_restarts=self._state.capture_restarts + 1,
                    )
                self._write_diagnostic_snapshot()
                self._notify_receive_error(detail)
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
                result = self._decode_period(period)
                decodes = result.decodes
            except (FT8DecoderError, OSError) as exc:
                detail = str(exc)
                self._set_state(status=FT8ReceiveStatus.DEGRADED, last_error=detail)
                self._notify_receive_error(detail)
                self._write_diagnostic_snapshot()
                continue

            for decode in decodes:
                self._activity_manager.ingest(decode)
            self._notify_decodes(decodes)
            snapshot = self._activity_manager.snapshot(current_period=period.period)
            session_state = None
            if self._diagnostic_session is not None:
                session_state = self._diagnostic_session.record(
                    result.primary,
                    result.comparison,
                )
            with self._state_lock:
                state = self._state
                recovered_status = (
                    FT8ReceiveStatus.RUNNING
                    if self._capture_healthy
                    else state.status
                )
                recovered_error = None if self._capture_healthy else state.last_error
                self._state = replace(
                    state,
                    status=recovered_status,
                    last_period=period.period,
                    decode_count=state.decode_count + len(decodes),
                    cq_decode_count=(
                        state.cq_decode_count
                        + sum(decode.kind is FT8MessageKind.CQ for decode in decodes)
                    ),
                    cq_activity=snapshot,
                    last_error=recovered_error,
                    last_decoder=result.primary,
                    last_comparison_decoder=result.comparison,
                    decoder_runs=state.decoder_runs + 1,
                    raw_decoder_lines=(
                        state.raw_decoder_lines + result.primary.raw_line_count
                    ),
                    malformed_decoder_lines=(
                        state.malformed_decoder_lines
                        + result.primary.malformed_line_count
                    ),
                    diagnostic_session=session_state,
                )
            self._write_diagnostic_snapshot()

    def _notify_decodes(self, decodes: tuple[FT8Decode, ...]) -> None:
        with self._observer_lock:
            observer = self._observer
        if observer is not None:
            observer.on_decodes(decodes)

    def _notify_receive_error(self, detail: str) -> None:
        with self._observer_lock:
            observer = self._observer
        if observer is not None:
            observer.on_receive_error(detail)

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
            self._state = replace(
                state,
                periods_dropped=state.periods_dropped + 1,
                last_error="decoder backlog: stale FT8 period dropped",
            )
        self._write_diagnostic_snapshot()

    def _record_capture(self, period: FT8PcmPeriod) -> None:
        audio = analyze_ft8_pcm(
            period.pcm_s16le,
            boundary_lateness_ms=period.boundary_lateness_ms,
        )
        clock, diagnostic_error = self._assess_clock_safely()
        with self._state_lock:
            saved_periods = self._state.saved_periods
        session_state = (
            None
            if self._diagnostic_session is None
            else self._diagnostic_session.latest_state
        )
        if (
            self._recorder is not None
            and (session_state is None or session_state.active)
        ):
            try:
                self._recorder.save(period)
                saved_periods = self._recorder.saved
            except OSError as error:
                diagnostic_error = f"could not save bounded FT8 PCM: {error}"
        with self._state_lock:
            state = self._state
            self._state = replace(
                state,
                last_period=period.period,
                periods_captured=state.periods_captured + 1,
                last_audio=audio,
                last_clock=clock,
                saved_periods=saved_periods,
                diagnostic_session=session_state,
                last_diagnostic_error=diagnostic_error,
            )
        self._write_diagnostic_snapshot()

    def _set_state(
        self,
        *,
        status: FT8ReceiveStatus,
        last_error: str | None | object = ...,
    ) -> None:
        with self._state_lock:
            state = self._state
            error = state.last_error if last_error is ... else last_error
            self._state = replace(
                state,
                status=status,
                last_error=error if isinstance(error, str) or error is None else None,
            )

    def _decode_period(self, period: FT8PcmPeriod) -> FT8DecoderResult:
        diagnostic_decode = getattr(self._decoder, "decode_with_diagnostics", None)
        if callable(diagnostic_decode):
            result = diagnostic_decode(period)
            if isinstance(result, FT8DecoderResult):
                return result

        started = time.monotonic()
        decodes = self._decoder.decode(period)
        dts = tuple(decode.dt_seconds for decode in decodes)
        diagnostics = FT8DecoderDiagnostics(
            backend=type(self._decoder).__name__,
            runtime_seconds=time.monotonic() - started,
            raw_line_count=len(decodes),
            parsed_decode_count=len(decodes),
            cq_decode_count=sum(
                decode.kind is FT8MessageKind.CQ for decode in decodes
            ),
            malformed_line_count=0,
            dt_min_seconds=min(dts) if dts else None,
            dt_max_seconds=max(dts) if dts else None,
        )
        return FT8DecoderResult(decodes=decodes, primary=diagnostics)

    def _assess_clock_safely(self) -> tuple[FT8ClockDiagnostics, str | None]:
        try:
            gps_utc = None if self._gps_utc is None else self._gps_utc()
            ntp = None if self._ntp_status is None else self._ntp_status()
            return (
                assess_ft8_clock(
                    system_utc=self._clock.now_utc(),
                    monotonic_seconds=self._clock.monotonic(),
                    gps_utc=gps_utc,
                    ntp=ntp,
                ),
                None,
            )
        except (OSError, RuntimeError, ValueError) as error:
            detail = f"clock readiness diagnostic failed: {error}"
            return (
                FT8ClockDiagnostics(
                    quality=FT8ClockQuality.UNVERIFIED,
                    detail=detail,
                ),
                detail,
            )

    def _write_diagnostic_snapshot(self) -> None:
        path = self._diagnostic_snapshot_path
        if path is None:
            return
        with self._state_lock:
            state = self._state
        with self._snapshot_lock:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_suffix(path.suffix + ".tmp")
                payload = diagnostic_json_value(state)
                temporary.write_text(
                    json.dumps(payload, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                os.replace(temporary, path)
            except OSError as error:
                # Diagnostics must never take down receive. The capture/decode state
                # remains available in memory even when the optional file is unwritable.
                with self._state_lock:
                    self._state = replace(
                        self._state,
                        last_diagnostic_error=(
                            f"could not write FT8 diagnostic snapshot: {error}"
                        ),
                    )
                return

    def _drain_queue(self) -> None:
        while True:
            try:
                self._periods.get_nowait()
            except queue.Empty:
                return
