"""Receive-only FT8 audio acquisition boundary and ALSA adapter."""

from __future__ import annotations

import subprocess
import threading
from dataclasses import dataclass
from typing import Protocol

from rolling_thunder.ft8.audio_buffer import (
    FT8AudioBuffer,
    FT8AudioBufferError,
)
from rolling_thunder.ft8.decoder import FT8PcmPeriod
from rolling_thunder.ft8.domain import FT8_PERIOD_SECONDS, FT8Period
from rolling_thunder.ft8.timing import FT8Clock, SystemFT8Clock

FT8_SAMPLE_RATE_HZ = 12_000
FT8_SAMPLE_WIDTH_BYTES = 2
FT8_PERIOD_SAMPLES = FT8_SAMPLE_RATE_HZ * FT8_PERIOD_SECONDS
FT8_PERIOD_BYTES = FT8_PERIOD_SAMPLES * FT8_SAMPLE_WIDTH_BYTES

# Keep continuous reads short so the software FT8 boundary cannot be displaced
# by a large userspace audio read.
FT8_CAPTURE_CHUNK_MS = 50
FT8_CAPTURE_CHUNK_BYTES = (
    FT8_SAMPLE_RATE_HZ
    * FT8_SAMPLE_WIDTH_BYTES
    * FT8_CAPTURE_CHUNK_MS
    // 1000
)


class FT8AudioInputError(RuntimeError):
    """Safe receive-audio failure."""


class FT8AudioInput(Protocol):
    """Project-owned receive-only PCM source."""

    def start(self) -> None:
        """Open continuous receive-only capture."""

    def read_period(self) -> FT8PcmPeriod:
        """Return one complete UTC-aligned mono S16_LE period."""

    def stop(self) -> None:
        """Cancel capture and release the device."""


@dataclass(frozen=True, slots=True)
class AlsaCaptureCommand:
    """Immutable command description used to launch receive-only arecord."""

    device: str
    sample_rate_hz: int = FT8_SAMPLE_RATE_HZ

    def argv(self) -> tuple[str, ...]:
        return (
            "arecord",
            "-q",
            "-D",
            self.device,
            "-f",
            "S16_LE",
            "-c",
            "1",
            "-r",
            str(self.sample_rate_hz),
            "-t",
            "raw",
            "-",
        )


class AlsaArecordFT8AudioInput:
    """Continuous receive-only ALSA capture with FT8 period extraction."""

    def __init__(
        self,
        device: str,
        *,
        clock: FT8Clock | None = None,
        sample_rate_hz: int = FT8_SAMPLE_RATE_HZ,
    ) -> None:
        normalized = device.strip()
        if not normalized:
            raise ValueError("FT8 audio device must not be blank")
        if sample_rate_hz != FT8_SAMPLE_RATE_HZ:
            raise ValueError("FT8 receive capture must use 12000 Hz")

        self._command = AlsaCaptureCommand(normalized, sample_rate_hz)
        self._clock = clock or SystemFT8Clock()
        self._stop_event = threading.Event()
        self._process: subprocess.Popen[bytes] | None = None
        self._reader_thread: threading.Thread | None = None
        self._reader_error: FT8AudioInputError | None = None
        self._buffer: FT8AudioBuffer | None = None
        self._next_period: FT8Period | None = None
        self._next_period_start_sample: int | None = None
        self._lock = threading.Lock()

    @property
    def device(self) -> str:
        return self._command.device

    def start(self) -> None:
        with self._lock:
            if self._process is not None:
                raise RuntimeError("FT8 audio input is already started")
            self._stop_event.clear()
            self._reader_error = None
            self._next_period = None
            self._next_period_start_sample = None
            buffer = FT8AudioBuffer()

        try:
            process = subprocess.Popen(
                self._command.argv(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as exc:
            raise FT8AudioInputError(f"could not start FT8 capture: {exc}") from exc

        if process.stdout is None:
            process.terminate()
            process.wait(timeout=2)
            raise FT8AudioInputError("FT8 capture stdout is unavailable")

        reader = threading.Thread(
            target=self._reader_loop,
            args=(process, buffer),
            name="ft8-alsa-reader",
            daemon=True,
        )

        with self._lock:
            if self._stop_event.is_set():
                process.terminate()
                process.wait(timeout=2)
                raise FT8AudioInputError("FT8 audio capture cancelled during start")
            self._process = process
            self._buffer = buffer
            self._reader_thread = reader

        reader.start()

    def read_period(self) -> FT8PcmPeriod:
        with self._lock:
            process = self._process
            buffer = self._buffer
            period = self._next_period
            start_sample = self._next_period_start_sample

        if process is None or buffer is None:
            raise FT8AudioInputError("FT8 audio input is not started")

        if period is None or start_sample is None:
            self._wait_for_initial_audio(process, buffer)

            now = self._clock.now_utc()
            current = FT8Period.from_utc(now)
            period = FT8Period(current.index + 1)
            wait_s = (period.start_utc - now).total_seconds()

            if wait_s > 0 and self._stop_event.wait(wait_s):
                raise FT8AudioInputError("FT8 audio capture cancelled")

            if self._clock.current_period() != period:
                raise FT8AudioInputError(
                    "system clock changed while aligning FT8 capture"
                )

            start_sample = buffer.next_sample

            with self._lock:
                self._next_period = period
                self._next_period_start_sample = start_sample

        end_sample = start_sample + FT8_PERIOD_SAMPLES
        self._wait_for_samples(process, buffer, end_sample)

        try:
            pcm = buffer.extract(
                start_sample=start_sample,
                sample_count=FT8_PERIOD_SAMPLES,
            )
        except FT8AudioBufferError as exc:
            raise FT8AudioInputError(f"could not extract FT8 period: {exc}") from exc

        next_period, next_start_sample = self._realign_next_period(
            buffer,
            completed_period=period,
        )

        with self._lock:
            if (
                self._next_period != period
                or self._next_period_start_sample != start_sample
            ):
                raise FT8AudioInputError(
                    "FT8 capture period identity changed unexpectedly"
                )

            self._next_period = next_period
            self._next_period_start_sample = next_start_sample

        return FT8PcmPeriod(
            period=period,
            sample_rate_hz=FT8_SAMPLE_RATE_HZ,
            pcm_s16le=pcm,
        )

    def _realign_next_period(
        self,
        buffer: FT8AudioBuffer,
        *,
        completed_period: FT8Period,
    ) -> tuple[FT8Period, int]:
        """Re-anchor the next PCM window to UTC so USB sample drift cannot accumulate.

        USB audio hardware and the Pi system clock are independent oscillators.
        Advancing forever by exactly 180,000 captured samples therefore causes
        the extracted FT8 windows to drift away from 15-second UTC boundaries
        during long runtimes. Re-anchor after every completed period so any
        sample-clock error is bounded to one FT8 period instead of accumulating
        across days or months.
        """
        next_period = FT8Period(completed_period.index + 1)
        now = self._clock.now_utc()

        if now < next_period.start_utc:
            wait_s = (next_period.start_utc - now).total_seconds()
            if wait_s > 0 and self._stop_event.wait(wait_s):
                raise FT8AudioInputError("FT8 audio capture cancelled")

        current = self._clock.current_period()

        if current.index < next_period.index:
            raise FT8AudioInputError(
                "system clock did not reach the expected FT8 boundary"
            )

        if current.index > next_period.index:
            # A long scheduling/system stall crossed one or more complete slots.
            # Skip stale slots and align to the next future UTC boundary rather
            # than mislabeling late audio as an earlier FT8 period.
            next_period = FT8Period(current.index + 1)
            wait_s = (next_period.start_utc - self._clock.now_utc()).total_seconds()
            if wait_s > 0 and self._stop_event.wait(wait_s):
                raise FT8AudioInputError("FT8 audio capture cancelled")
            if self._clock.current_period() != next_period:
                raise FT8AudioInputError(
                    "system clock changed while re-aligning FT8 capture"
                )

        return next_period, buffer.next_sample

    def stop(self) -> None:
        self._stop_event.set()

        with self._lock:
            process = self._process
            reader = self._reader_thread
            self._process = None
            self._reader_thread = None
            self._buffer = None
            self._next_period = None
            self._next_period_start_sample = None

        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)

        if reader is not None:
            reader.join(timeout=2)

        if process is not None:
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()

    def _reader_loop(
        self,
        process: subprocess.Popen[bytes],
        buffer: FT8AudioBuffer,
    ) -> None:
        if process.stdout is None:
            self._set_reader_error("FT8 capture stdout is unavailable")
            return

        while not self._stop_event.is_set():
            try:
                chunk = process.stdout.read(FT8_CAPTURE_CHUNK_BYTES)
            except OSError as exc:
                if not self._stop_event.is_set():
                    self._set_reader_error(f"FT8 audio capture read failed: {exc}")
                return

            if not chunk:
                if not self._stop_event.is_set():
                    detail = ""
                    if process.stderr is not None and process.poll() is not None:
                        detail = process.stderr.read().decode(
                            errors="replace"
                        ).strip()
                    suffix = f": {detail}" if detail else ""
                    self._set_reader_error(
                        f"FT8 capture ended unexpectedly{suffix}"
                    )
                return

            try:
                buffer.append(chunk)
            except FT8AudioBufferError as exc:
                self._set_reader_error(f"invalid FT8 capture audio: {exc}")
                return

    def _wait_for_initial_audio(
        self,
        process: subprocess.Popen[bytes],
        buffer: FT8AudioBuffer,
    ) -> None:
        while buffer.next_sample == 0:
            self._raise_if_capture_failed(process)

            if self._stop_event.wait(0.05):
                raise FT8AudioInputError("FT8 audio capture cancelled")

    def _wait_for_samples(
        self,
        process: subprocess.Popen[bytes],
        buffer: FT8AudioBuffer,
        end_sample: int,
    ) -> None:
        while not buffer.wait_for_sample(end_sample, timeout_s=0.1):
            self._raise_if_capture_failed(process)

            if self._stop_event.is_set():
                raise FT8AudioInputError("FT8 audio capture cancelled")

    def _raise_if_capture_failed(
        self,
        process: subprocess.Popen[bytes],
    ) -> None:
        with self._lock:
            reader_error = self._reader_error

        if reader_error is not None:
            raise reader_error

        if process.poll() is not None:
            raise FT8AudioInputError("FT8 capture process exited unexpectedly")

    def _set_reader_error(self, detail: str) -> None:
        with self._lock:
            if self._reader_error is None:
                self._reader_error = FT8AudioInputError(detail)

    def _read_exact(self, process: subprocess.Popen[bytes], size: int) -> bytes:
        """Legacy bounded read helper retained for regression coverage."""
        if process.stdout is None:
            raise FT8AudioInputError("FT8 capture stdout is unavailable")

        chunks: list[bytes] = []
        remaining = size

        while remaining:
            if self._stop_event.is_set():
                raise FT8AudioInputError("FT8 audio capture cancelled")

            chunk = process.stdout.read(remaining)

            if not chunk:
                detail = ""
                if process.stderr is not None:
                    detail = process.stderr.read().decode(
                        errors="replace"
                    ).strip()
                suffix = f": {detail}" if detail else ""
                raise FT8AudioInputError(
                    f"FT8 capture ended before a complete period{suffix}"
                )

            chunks.append(chunk)
            remaining -= len(chunk)

        return b"".join(chunks)
