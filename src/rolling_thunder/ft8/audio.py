"""Receive-only FT8 audio acquisition boundary and ALSA adapter."""

from __future__ import annotations

import subprocess
import threading
from dataclasses import dataclass
from typing import Protocol

from rolling_thunder.ft8.decoder import FT8PcmPeriod
from rolling_thunder.ft8.domain import FT8_PERIOD_SECONDS, FT8Period
from rolling_thunder.ft8.timing import FT8Clock, SystemFT8Clock

FT8_SAMPLE_RATE_HZ = 12_000
FT8_SAMPLE_WIDTH_BYTES = 2
FT8_PERIOD_BYTES = FT8_SAMPLE_RATE_HZ * FT8_SAMPLE_WIDTH_BYTES * FT8_PERIOD_SECONDS


class FT8AudioInputError(RuntimeError):
    """Safe receive-audio failure."""


class FT8AudioInput(Protocol):
    """Project-owned receive-only PCM source."""

    def start(self) -> None:
        """Open capture at a clean UTC FT8 period boundary."""

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
    """Persistent receive-only ALSA capture aligned to UTC FT8 periods."""

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
        self._next_period: FT8Period | None = None
        self._lock = threading.Lock()

    @property
    def device(self) -> str:
        return self._command.device

    def start(self) -> None:
        with self._lock:
            if self._process is not None:
                raise RuntimeError("FT8 audio input is already started")
            self._stop_event.clear()

        now = self._clock.now_utc()
        current = FT8Period.from_utc(now)
        target = FT8Period(current.index + 1)
        wait_s = (target.start_utc - now).total_seconds()
        if wait_s > 0 and self._stop_event.wait(wait_s):
            raise FT8AudioInputError("FT8 audio capture cancelled before start")

        if self._clock.current_period() != target:
            raise FT8AudioInputError("system clock changed while aligning FT8 capture")

        try:
            process = subprocess.Popen(
                self._command.argv(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as exc:
            raise FT8AudioInputError(f"could not start FT8 capture: {exc}") from exc

        with self._lock:
            if self._stop_event.is_set():
                process.terminate()
                process.wait(timeout=2)
                raise FT8AudioInputError("FT8 audio capture cancelled during start")
            self._process = process
            self._next_period = target

    def read_period(self) -> FT8PcmPeriod:
        with self._lock:
            process = self._process
            period = self._next_period
        if process is None or period is None or process.stdout is None:
            raise FT8AudioInputError("FT8 audio input is not started")

        pcm = self._read_exact(process, FT8_PERIOD_BYTES)
        with self._lock:
            if self._next_period != period:
                raise FT8AudioInputError("FT8 capture period identity changed unexpectedly")
            self._next_period = FT8Period(period.index + 1)

        return FT8PcmPeriod(
            period=period,
            sample_rate_hz=FT8_SAMPLE_RATE_HZ,
            pcm_s16le=pcm,
        )

    def stop(self) -> None:
        self._stop_event.set()
        with self._lock:
            process = self._process
            self._process = None
            self._next_period = None
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()

    def _read_exact(self, process: subprocess.Popen[bytes], size: int) -> bytes:
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
                    detail = process.stderr.read().decode(errors="replace").strip()
                suffix = f": {detail}" if detail else ""
                raise FT8AudioInputError(f"FT8 capture ended before a complete period{suffix}")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)
