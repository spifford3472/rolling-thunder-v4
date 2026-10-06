"""Receive-only FT8 decoder boundary and saved-WAV subprocess adapters."""

from __future__ import annotations

import re
import subprocess
import tempfile
import time
import wave
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from rolling_thunder.ft8.domain import FT8Decode, FT8MessageKind, FT8Period

_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"
_FT8MON_LINE = re.compile(
    rf"^\s*\d{{6}}\s+(?P<snr>[+-]?\d+)\s+"
    r"(?P<correct_bits>\d+)\s+"
    rf"(?P<dt>{_NUMBER})\s+"
    rf"(?P<freq>{_NUMBER})\s+(?P<message>.+?)\s*$"
)
_FT8LIB_LINE = re.compile(
    rf"^\s*\d{{6}}\s+(?P<snr>{_NUMBER})\s+"
    rf"(?P<dt>{_NUMBER})\s+"
    rf"(?P<freq>{_NUMBER})\s+(?:~\s+)?(?P<message>.+?)\s*$"
)
_REPORT = re.compile(r"^[+-]\d{2}$")
_R_REPORT = re.compile(r"^R([+-]\d{2})$")


class FT8DecoderError(RuntimeError):
    """Safe receive-decoder failure."""


@dataclass(frozen=True, slots=True)
class FT8PcmPeriod:
    """One mono signed-16-bit PCM buffer associated with an explicit FT8 period."""

    period: FT8Period
    sample_rate_hz: int
    pcm_s16le: bytes
    boundary_lateness_ms: float = 0.0

    def __post_init__(self) -> None:
        if self.sample_rate_hz <= 0:
            raise ValueError("sample_rate_hz must be positive")
        if not self.pcm_s16le:
            raise ValueError("pcm_s16le must not be empty")
        if len(self.pcm_s16le) % 2:
            raise ValueError("pcm_s16le must contain complete signed 16-bit samples")
        if self.boundary_lateness_ms < 0:
            raise ValueError("boundary_lateness_ms must not be negative")

    @classmethod
    def from_wav(cls, path: Path, *, period: FT8Period) -> FT8PcmPeriod:
        """Load a mono 16-bit PCM WAV used by the Checkpoint 3 benchmark harness."""
        with wave.open(str(path), "rb") as source:
            if source.getnchannels() != 1:
                raise FT8DecoderError("FT8 reference WAV must be mono")
            if source.getsampwidth() != 2:
                raise FT8DecoderError("FT8 reference WAV must contain 16-bit PCM")
            frames = source.readframes(source.getnframes())
            sample_rate_hz = source.getframerate()
        return cls(period=period, sample_rate_hz=sample_rate_hz, pcm_s16le=frames)


class FT8Decoder(Protocol):
    """Project-owned decoder contract; backend-specific objects never escape it."""

    def decode(self, pcm: FT8PcmPeriod) -> tuple[FT8Decode, ...]:
        """Decode one explicitly identified FT8 period."""


@dataclass(frozen=True, slots=True)
class FT8DecoderDiagnostics:
    """Bounded measurements from one decoder subprocess invocation."""

    backend: str
    runtime_seconds: float
    raw_line_count: int
    parsed_decode_count: int
    cq_decode_count: int
    malformed_line_count: int
    dt_min_seconds: float | None = None
    dt_max_seconds: float | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class FT8DecoderResult:
    """Normalized decoder output plus diagnostics for the exact same PCM."""

    decodes: tuple[FT8Decode, ...]
    primary: FT8DecoderDiagnostics
    comparison: FT8DecoderDiagnostics | None = None


class FT8DiagnosticDecoder(Protocol):
    def decode_with_diagnostics(self, pcm: FT8PcmPeriod) -> FT8DecoderResult: ...


@dataclass(frozen=True, slots=True)
class ParsedFT8Message:
    """Normalized fields extracted from common FT8 QSO message text."""

    kind: FT8MessageKind
    source_callsign: str | None = None
    destination_callsign: str | None = None
    grid: str | None = None
    report_db: int | None = None
    cq_qualifier: str | None = None


def parse_ft8_message(message: str) -> ParsedFT8Message:
    """Parse common QSO messages without making selection or QSO decisions."""
    tokens = message.strip().upper().split()
    if not tokens:
        return ParsedFT8Message(kind=FT8MessageKind.OTHER)

    if tokens[0] == "CQ":
        if len(tokens) >= 3 and _looks_like_grid(tokens[-1]):
            source_index = len(tokens) - 2
            qualifier = " ".join(tokens[1:source_index]) or None
            return ParsedFT8Message(
                kind=FT8MessageKind.CQ,
                source_callsign=tokens[source_index],
                grid=tokens[-1],
                cq_qualifier=qualifier,
            )
        if len(tokens) >= 2:
            qualifier = " ".join(tokens[1:-1]) or None
            return ParsedFT8Message(
                kind=FT8MessageKind.CQ,
                source_callsign=tokens[-1],
                cq_qualifier=qualifier,
            )
        return ParsedFT8Message(kind=FT8MessageKind.OTHER)

    if len(tokens) >= 3:
        destination = tokens[0]
        source = tokens[1]
        payload = tokens[2]
        if _REPORT.fullmatch(payload):
            return ParsedFT8Message(
                kind=FT8MessageKind.REPORT,
                source_callsign=source,
                destination_callsign=destination,
                report_db=int(payload),
            )
        r_report = _R_REPORT.fullmatch(payload)
        if r_report is not None:
            return ParsedFT8Message(
                kind=FT8MessageKind.R_REPORT,
                source_callsign=source,
                destination_callsign=destination,
                report_db=int(r_report.group(1)),
            )
        if payload in {"RRR", "RR73", "73"}:
            return ParsedFT8Message(
                kind=FT8MessageKind.ACK_73,
                source_callsign=source,
                destination_callsign=destination,
            )

    return ParsedFT8Message(kind=FT8MessageKind.OTHER)


class _SavedWavSubprocessDecoder:
    """Common receive-only saved-WAV subprocess lifecycle."""

    def __init__(self, executable: str, *, timeout_s: float = 12.0) -> None:
        if not executable.strip():
            raise ValueError("executable must not be blank")
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        self._executable = executable
        self._timeout_s = timeout_s

    def decode(self, pcm: FT8PcmPeriod) -> tuple[FT8Decode, ...]:
        return self.decode_with_diagnostics(pcm).decodes

    def decode_with_diagnostics(self, pcm: FT8PcmPeriod) -> FT8DecoderResult:
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="rolling-thunder-ft8-") as tmp:
            wav_path = Path(tmp) / "period.wav"
            _write_wav(wav_path, pcm)
            try:
                completed = subprocess.run(
                    self._command(wav_path),
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=self._timeout_s,
                )
            except subprocess.TimeoutExpired as exc:
                raise FT8DecoderError(
                    f"{self.backend_name} decoder timed out after {self._timeout_s:.1f}s"
                ) from exc
            except OSError as exc:
                raise FT8DecoderError(
                    f"{self.backend_name} decoder could not start: {exc}"
                ) from exc

        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise FT8DecoderError(
                f"{self.backend_name} decoder exited {completed.returncode}: {detail}"
            )

        decodes: list[FT8Decode] = []
        raw_lines = tuple(line for line in completed.stdout.splitlines() if line.strip())
        malformed = 0
        for line in raw_lines:
            parsed = self._parse_line(line, period=pcm.period)
            if parsed is not None:
                decodes.append(parsed)
            elif _looks_like_decoder_data(line):
                malformed += 1
        normalized = tuple(decodes)
        dts = tuple(decode.dt_seconds for decode in normalized)
        diagnostics = FT8DecoderDiagnostics(
            backend=self.backend_name,
            runtime_seconds=time.monotonic() - started,
            raw_line_count=len(raw_lines),
            parsed_decode_count=len(normalized),
            cq_decode_count=sum(
                decode.kind is FT8MessageKind.CQ for decode in normalized
            ),
            malformed_line_count=malformed,
            dt_min_seconds=min(dts) if dts else None,
            dt_max_seconds=max(dts) if dts else None,
        )
        return FT8DecoderResult(decodes=normalized, primary=diagnostics)

    @property
    def backend_name(self) -> str:
        raise NotImplementedError

    def _command(self, wav_path: Path) -> list[str]:
        raise NotImplementedError

    def _parse_line(self, line: str, *, period: FT8Period) -> FT8Decode | None:
        raise NotImplementedError


class Ft8monDecoder(_SavedWavSubprocessDecoder):
    """Adapter for rtmrtmrtmrtm/ft8mon saved-WAV output."""

    @property
    def backend_name(self) -> str:
        return "ft8mon"

    def _command(self, wav_path: Path) -> list[str]:
        return [self._executable, "-file", str(wav_path)]

    def _parse_line(self, line: str, *, period: FT8Period) -> FT8Decode | None:
        match = _FT8MON_LINE.match(line)
        if match is None:
            return None
        return _normalized_decode(
            period=period,
            snr_db=int(match.group("snr")),
            dt_seconds=float(match.group("dt")),
            audio_frequency_hz=round(float(match.group("freq"))),
            message=match.group("message"),
            backend="ft8mon",
            metadata={"correct_bits": match.group("correct_bits")},
        )


class Ft8LibDecoder(_SavedWavSubprocessDecoder):
    """Adapter for kgoba/ft8_lib decode_ft8 saved-WAV output."""

    @property
    def backend_name(self) -> str:
        return "kgoba/ft8_lib"

    def _command(self, wav_path: Path) -> list[str]:
        return [self._executable, str(wav_path)]

    def _parse_line(self, line: str, *, period: FT8Period) -> FT8Decode | None:
        match = _FT8LIB_LINE.match(line)
        if match is None:
            return None
        raw_snr = float(match.group("snr"))
        return _normalized_decode(
            period=period,
            snr_db=round(raw_snr),
            dt_seconds=float(match.group("dt")),
            audio_frequency_hz=round(float(match.group("freq"))),
            message=match.group("message"),
            backend="kgoba/ft8_lib",
            metadata={"raw_snr": match.group("snr")},
        )


class ComparingFT8Decoder:
    """Run two decoder adapters against one immutable PCM period."""

    def __init__(
        self,
        primary: FT8DiagnosticDecoder,
        comparison: FT8DiagnosticDecoder,
        *,
        comparison_enabled: Callable[[], bool] | None = None,
    ) -> None:
        self._primary = primary
        self._comparison = comparison
        self._comparison_enabled = comparison_enabled or (lambda: True)

    def decode(self, pcm: FT8PcmPeriod) -> tuple[FT8Decode, ...]:
        return self.decode_with_diagnostics(pcm).decodes

    def decode_with_diagnostics(self, pcm: FT8PcmPeriod) -> FT8DecoderResult:
        primary = self._primary.decode_with_diagnostics(pcm)
        if not self._comparison_enabled():
            return primary
        try:
            comparison = self._comparison.decode_with_diagnostics(pcm).primary
        except FT8DecoderError as error:
            comparison = FT8DecoderDiagnostics(
                backend=type(self._comparison).__name__,
                runtime_seconds=0.0,
                raw_line_count=0,
                parsed_decode_count=0,
                cq_decode_count=0,
                malformed_line_count=0,
                error=str(error),
            )
        return FT8DecoderResult(
            decodes=primary.decodes,
            primary=primary.primary,
            comparison=comparison,
        )


def _normalized_decode(
    *,
    period: FT8Period,
    snr_db: int,
    dt_seconds: float,
    audio_frequency_hz: int,
    message: str,
    backend: str,
    metadata: dict[str, str] | None = None,
) -> FT8Decode:
    parsed = parse_ft8_message(message)
    backend_metadata = {"decoder": backend}
    if metadata is not None:
        backend_metadata.update(metadata)
    try:
        return FT8Decode(
            period=period,
            snr_db=snr_db,
            dt_seconds=dt_seconds,
            audio_frequency_hz=audio_frequency_hz,
            raw_message=message,
            kind=parsed.kind,
            source_callsign=parsed.source_callsign,
            destination_callsign=parsed.destination_callsign,
            grid=parsed.grid,
            report_db=parsed.report_db,
            cq_qualifier=parsed.cq_qualifier,
            backend_metadata=backend_metadata,
        )
    except ValueError:
        return FT8Decode(
            period=period,
            snr_db=snr_db,
            dt_seconds=dt_seconds,
            audio_frequency_hz=audio_frequency_hz,
            raw_message=message,
            kind=FT8MessageKind.OTHER,
            backend_metadata={**backend_metadata, "normalization": "partial"},
        )


def _looks_like_grid(value: str) -> bool:
    if len(value) not in {4, 6, 8}:
        return False
    return value[:2].isalpha() and value[2:4].isdigit()


def _looks_like_decoder_data(line: str) -> bool:
    return re.match(r"^\s*\d{6}\s+", line) is not None


def _write_wav(path: Path, pcm: FT8PcmPeriod) -> None:
    with wave.open(str(path), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(pcm.sample_rate_hz)
        target.writeframes(pcm.pcm_s16le)
