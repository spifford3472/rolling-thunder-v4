"""Offline FT8 message construction, encoding, and waveform generation.

Checkpoint 5 deliberately ends at immutable in-memory PCM. This module has no
audio-device, CAT, PTT, runtime-worker, or RF authority.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from rolling_thunder.ft8.transmit import FT8TransmitKind, FT8TransmitRequest

FT8_SAMPLE_RATE_HZ = 12_000
FT8_CHANNEL_SYMBOLS = 79
FT8_SYMBOL_DURATION_S = 0.160
FT8_TONE_SPACING_HZ = 6.25
FT8_OCCUPIED_DURATION_S = FT8_CHANNEL_SYMBOLS * FT8_SYMBOL_DURATION_S
FT8_SLOT_SAMPLES = 15 * FT8_SAMPLE_RATE_HZ
FT8_PCM_SAMPLE_WIDTH_BYTES = 2

_PACKED_RE = re.compile(r"^Packed data:\\s+((?:[0-9a-fA-F]{2}\\s+){9}[0-9a-fA-F]{2})\\s*$")
_TONES_RE = re.compile(r"^FSK tones:\\s+([0-7]{79})\\s*$")


class FT8EncoderError(RuntimeError):
    """Safe offline FT8 encoder failure."""


@dataclass(frozen=True, slots=True)
class FT8EncodedMessage:
    """Backend-independent immutable FT8 encoding result."""

    message: str
    packed_payload: bytes
    tones: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class FT8Waveform:
    """Immutable mono signed-16-bit little-endian FT8 slot waveform."""

    encoded: FT8EncodedMessage
    base_frequency_hz: int
    sample_rate_hz: int
    pcm_s16le: bytes

    @property
    def sample_count(self) -> int:
        return len(self.pcm_s16le) // FT8_PCM_SAMPLE_WIDTH_BYTES


class FT8Encoder(Protocol):
    """Project-owned offline FT8 encoder boundary."""

    def encode(self, message: str, *, base_frequency_hz: int) -> FT8Waveform:
        """Encode one exact FT8 message to immutable in-memory PCM."""
        ...


def format_signal_report(report_db: int, *, acknowledged: bool = False) -> str:
    """Format one standard FT8 signal report."""
    if not -50 <= report_db <= 49:
        raise ValueError("FT8 signal report must be between -50 and +49 dB")
    prefix = "R" if acknowledged else ""
    return f"{prefix}{report_db:+03d}"


def message_from_transmit_request(request: FT8TransmitRequest) -> str:
    """Map an already-authorized logical request to exact FT8 protocol text."""
    context = request.context
    remote = context.remote_callsign
    local = context.local_callsign
    if request.kind is FT8TransmitKind.CALL:
        return f"{remote} {local} {context.local_grid[:4]}"
    if request.kind is FT8TransmitKind.REPORT:
        return f"{remote} {local} {format_signal_report(context.signal_report_db)}"
    if request.kind is FT8TransmitKind.R_REPORT:
        return (
            f"{remote} {local} "
            f"{format_signal_report(context.signal_report_db, acknowledged=True)}"
        )
    if request.kind is FT8TransmitKind.SEVENTY_THREE:
        return f"{remote} {local} 73"
    raise ValueError(f"unsupported FT8 transmit kind: {request.kind}")


class Ft8LibEncoder:
    """Offline adapter for the pinned kgoba/ft8_lib gen_ft8 executable."""

    def __init__(self, executable: str | Path, *, timeout_s: float = 5.0) -> None:
        path = Path(executable)
        if not path.is_absolute():
            raise ValueError("FT8 encoder executable must be an absolute path")
        if timeout_s <= 0:
            raise ValueError("FT8 encoder timeout must be positive")
        self._executable = path
        self._timeout_s = timeout_s

    def encode(self, message: str, *, base_frequency_hz: int) -> FT8Waveform:
        normalized = " ".join(message.strip().upper().split())
        if not normalized:
            raise ValueError("FT8 message must not be blank")
        if base_frequency_hz <= 0:
            raise ValueError("FT8 base frequency must be positive")

        with tempfile.TemporaryDirectory(prefix="rolling-thunder-ft8-") as directory:
            wav_path = Path(directory) / "encoded.wav"
            try:
                completed = subprocess.run(
                    [
                        str(self._executable),
                        normalized,
                        str(wav_path),
                        str(base_frequency_hz),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=self._timeout_s,
                )
            except OSError as exc:
                raise FT8EncoderError(f"could not start FT8 encoder: {exc}") from exc
            except subprocess.TimeoutExpired as exc:
                raise FT8EncoderError("FT8 encoder timed out") from exc

            if completed.returncode != 0:
                detail = completed.stderr.strip() or completed.stdout.strip()
                suffix = f": {detail}" if detail else ""
                raise FT8EncoderError(
                    f"FT8 encoder exited {completed.returncode}{suffix}"
                )

            encoded = self._parse_output(normalized, completed.stdout)
            pcm = self._read_reference_wav(wav_path)

        return FT8Waveform(
            encoded=encoded,
            base_frequency_hz=base_frequency_hz,
            sample_rate_hz=FT8_SAMPLE_RATE_HZ,
            pcm_s16le=pcm,
        )

    @staticmethod
    def _parse_output(message: str, output: str) -> FT8EncodedMessage:
        packed: bytes | None = None
        tones: tuple[int, ...] | None = None
        for line in output.splitlines():
            packed_match = _PACKED_RE.fullmatch(line.strip())
            if packed_match is not None:
                packed = bytes.fromhex(packed_match.group(1))
                continue
            tones_match = _TONES_RE.fullmatch(line.strip())
            if tones_match is not None:
                tones = tuple(int(value) for value in tones_match.group(1))

        if packed is None or len(packed) != 10:
            raise FT8EncoderError("FT8 encoder returned invalid packed payload")
        if tones is None or len(tones) != FT8_CHANNEL_SYMBOLS:
            raise FT8EncoderError("FT8 encoder returned invalid tone sequence")
        return FT8EncodedMessage(message=message, packed_payload=packed, tones=tones)

    @staticmethod
    def _read_reference_wav(path: Path) -> bytes:
        try:
            with wave.open(str(path), "rb") as source:
                channels = source.getnchannels()
                sample_width = source.getsampwidth()
                sample_rate = source.getframerate()
                sample_count = source.getnframes()
                pcm = source.readframes(sample_count)
        except (OSError, wave.Error) as exc:
            raise FT8EncoderError(f"FT8 encoder returned invalid WAV: {exc}") from exc

        if channels != 1:
            raise FT8EncoderError("FT8 waveform must be mono")
        if sample_width != FT8_PCM_SAMPLE_WIDTH_BYTES:
            raise FT8EncoderError("FT8 waveform must use signed 16-bit PCM")
        if sample_rate != FT8_SAMPLE_RATE_HZ:
            raise FT8EncoderError("FT8 waveform must use 12000 Hz")
        if sample_count != FT8_SLOT_SAMPLES:
            raise FT8EncoderError(
                f"FT8 waveform must contain {FT8_SLOT_SAMPLES} samples"
            )
        if len(pcm) != FT8_SLOT_SAMPLES * FT8_PCM_SAMPLE_WIDTH_BYTES:
            raise FT8EncoderError("FT8 waveform PCM byte count is inconsistent")
        return pcm
