"""In-memory WSPR-2 PCM decode using the project's pipe-only native helper."""

from __future__ import annotations

import math
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from time import monotonic
from typing import Protocol

WSPR_SAMPLE_RATE_HZ = 12_000
WSPR_WINDOW_SECONDS = 114
WSPR_PCM_BYTES = WSPR_WINDOW_SECONDS * WSPR_SAMPLE_RATE_HZ * 2
WSPR_DECODER_EXECUTABLE = "rolling-thunder-wsprd"
_FINISHED = b"<DecodeFinished>"
_MAX_SPOTS = 50
_MAX_STDOUT_BYTES = 4096
_CALLSIGN = re.compile(r"[A-Z0-9]{1,10}(?:/[A-Z0-9]{1,10}){0,2}\Z")
_LOCATOR = re.compile(r"[A-R]{2}[0-9]{2}(?:[A-X]{2})?\Z")


@dataclass(frozen=True, slots=True)
class WsprDecode:
    """One transient decoded WSPR report."""

    callsign: str
    locator: str | None
    frequency_hz: int
    snr_db: int
    time_offset_s: float
    drift_hz: int
    power_dbm: int


class WsprDecoderError(RuntimeError):
    """A decode failure whose message contains no audio or station identities."""


class WsprDecoder(Protocol):
    """Receiver-facing decoder interface with one bounded native invocation per slot."""

    @property
    def available(self) -> bool: ...

    def decode(
        self, pcm_s16le: bytes, dial_frequency_hz: int, cancel: Event
    ) -> tuple[WsprDecode, ...]: ...


class PipeWsprDecoder:
    """Run the dedicated WSPR helper without filenames or decoder journals."""

    def __init__(
        self, executable: str = WSPR_DECODER_EXECUTABLE, *, timeout_s: float = 25.0
    ) -> None:
        if not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("WSPR decoder timeout must be finite and positive.")
        self._requested_executable = executable
        self._timeout_s = timeout_s

    def _resolve_executable(self) -> str | None:
        # The deployed service calls the virtual environment's entry point directly.
        # Its PATH need not contain the environment's scripts directory.
        if self._requested_executable == WSPR_DECODER_EXECUTABLE:
            installed = Path(sys.executable).with_name(WSPR_DECODER_EXECUTABLE)
            if resolved := shutil.which(installed):
                return resolved
        return shutil.which(self._requested_executable)

    @property
    def available(self) -> bool:
        """Report whether the pipe-only executable is installed."""
        return self._resolve_executable() is not None

    def decode(
        self, pcm_s16le: bytes, dial_frequency_hz: int, cancel: Event
    ) -> tuple[WsprDecode, ...]:
        """Decode exactly one UTC-aligned WSPR-2 PCM window."""
        if cancel.is_set():
            return ()
        if len(pcm_s16le) != WSPR_PCM_BYTES:
            raise WsprDecoderError("WSPR audio window is incomplete.")
        executable = self._resolve_executable()
        if executable is None:
            raise WsprDecoderError("The pipe-only WSPR decoder is unavailable.")

        try:
            with subprocess.Popen(
                (executable, str(dial_frequency_hz)),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            ) as process:
                deadline = monotonic() + self._timeout_s
                pending_input: bytes | None = pcm_s16le
                try:
                    while not cancel.is_set():
                        remaining = deadline - monotonic()
                        if remaining <= 0.0:
                            raise WsprDecoderError("WSPR decoding timed out.")
                        try:
                            output, _ = process.communicate(pending_input, timeout=min(0.1, remaining))
                        except subprocess.TimeoutExpired:
                            pending_input = None
                            continue
                        if cancel.is_set():
                            return ()
                        if process.returncode != 0:
                            raise WsprDecoderError("WSPR decoding failed.")
                        return _decode_spots(output, dial_frequency_hz)
                finally:
                    if process.poll() is None:
                        process.kill()
        except OSError:
            raise WsprDecoderError("Could not run the pipe-only WSPR decoder.") from None
        return ()


def _decode_spots(output: bytes, dial_frequency_hz: int) -> tuple[WsprDecode, ...]:
    """Parse the helper's bounded line protocol without exposing raw output."""
    if len(output) > _MAX_STDOUT_BYTES:
        raise WsprDecoderError("Invalid WSPR decoder output.")
    lines = output.splitlines()
    if not lines or len(lines) > _MAX_SPOTS + 1 or lines[-1] != _FINISHED:
        raise WsprDecoderError("Incomplete WSPR decoder output.")

    results: list[WsprDecode] = []
    for line in lines[:-1]:
        try:
            fields = line.decode("ascii").split()
            if len(fields) not in {6, 7}:
                continue
            snr, time_offset, frequency, drift, callsign, *trailing = fields
            callsign = callsign.removeprefix("<").removesuffix(">")
            if not _CALLSIGN.fullmatch(callsign) or not any(char.isdigit() for char in callsign):
                continue
            locator = trailing[0].upper() if len(trailing) == 2 else ""
            snr_db, frequency_hz, drift_hz = int(snr), int(frequency), int(drift)
            power_dbm, time_offset_s = int(trailing[-1]), float(time_offset)
        except (UnicodeError, ValueError):
            continue

        if (
            not 1_300 <= frequency_hz - dial_frequency_hz <= 1_700
            or not 0 <= power_dbm <= 62
            or not math.isfinite(time_offset_s)
        ):
            continue
        results.append(
            WsprDecode(
                callsign=callsign,
                locator=locator if _LOCATOR.fullmatch(locator) else None,
                frequency_hz=frequency_hz,
                snr_db=snr_db,
                time_offset_s=time_offset_s,
                drift_hz=drift_hz,
                power_dbm=power_dbm,
            )
        )
    return tuple(results)
