"""Tests for Checkpoint 5 offline FT8 encoding and waveform boundaries."""

from __future__ import annotations

import hashlib
import os
import subprocess
import wave
from datetime import UTC, datetime
from pathlib import Path

import pytest

from rolling_thunder.ft8.domain import FT8Period, FT8PeriodParity, FT8QsoContext
from rolling_thunder.ft8.encoder import (
    FT8_CHANNEL_SYMBOLS,
    FT8_OCCUPIED_DURATION_S,
    FT8_SAMPLE_RATE_HZ,
    FT8_SLOT_SAMPLES,
    FT8_SYMBOL_DURATION_S,
    FT8_TONE_SPACING_HZ,
    FT8EncoderError,
    Ft8LibEncoder,
    format_signal_report,
    message_from_transmit_request,
)
from rolling_thunder.ft8.transmit import FT8TransmitKind, FT8TransmitRequest


def _context(report: int = -10) -> FT8QsoContext:
    return FT8QsoContext(
        local_callsign="KI5VNB",
        remote_callsign="K1ABC",
        target_audio_frequency_hz=1500,
        radio_frequency_hz=14_074_000,
        radio_band="20m",
        radio_mode="DIG-U",
        local_grid="EM79xm",
        tx_parity=FT8PeriodParity.ODD,
        authorized_period=FT8Period(index=100),
        authorized_utc=datetime.fromtimestamp(1501, tz=UTC),
        signal_report_db=report,
    )


def _request(kind: FT8TransmitKind, report: int = -10) -> FT8TransmitRequest:
    return FT8TransmitRequest(
        context=_context(report),
        kind=kind,
        period=FT8Period(index=101),
        attempt=1,
    )


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (FT8TransmitKind.CALL, "K1ABC KI5VNB EM79"),
        (FT8TransmitKind.REPORT, "K1ABC KI5VNB -10"),
        (FT8TransmitKind.R_REPORT, "K1ABC KI5VNB R-10"),
        (FT8TransmitKind.SEVENTY_THREE, "K1ABC KI5VNB 73"),
    ],
)
def test_transmit_request_maps_to_exact_protocol_text(
    kind: FT8TransmitKind, expected: str
) -> None:
    assert message_from_transmit_request(_request(kind)) == expected


@pytest.mark.parametrize(
    ("report", "acknowledged", "expected"),
    [
        (-50, False, "-50"),
        (-1, False, "-01"),
        (0, False, "+00"),
        (5, True, "R+05"),
        (49, True, "R+49"),
    ],
)
def test_signal_report_format(
    report: int, acknowledged: bool, expected: str
) -> None:
    assert format_signal_report(report, acknowledged=acknowledged) == expected


@pytest.mark.parametrize("report", [-51, 50])
def test_signal_report_rejects_unsupported_range(report: int) -> None:
    with pytest.raises(ValueError, match="between -50 and"):
        format_signal_report(report)


def test_reference_modulation_constants() -> None:
    assert FT8_CHANNEL_SYMBOLS == 79
    assert FT8_SYMBOL_DURATION_S == 0.160
    assert FT8_TONE_SPACING_HZ == 6.25
    assert FT8_OCCUPIED_DURATION_S == pytest.approx(12.64)
    assert FT8_SAMPLE_RATE_HZ == 12_000
    assert FT8_SLOT_SAMPLES == 180_000


def test_ft8_lib_adapter_returns_immutable_in_memory_pcm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(
        argv: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        wav_path = Path(argv[2])
        with wave.open(str(wav_path), "wb") as target:
            target.setnchannels(1)
            target.setsampwidth(2)
            target.setframerate(FT8_SAMPLE_RATE_HZ)
            target.writeframes(b"\x00\x00" * FT8_SLOT_SAMPLES)
        return subprocess.CompletedProcess(
            args=argv,
            returncode=0,
            stdout=(
                "Packed data: 01 02 03 04 05 06 07 08 09 0a\n"
                f"FSK tones: {'0' * FT8_CHANNEL_SYMBOLS}\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    encoder = Ft8LibEncoder("/opt/ft8_lib/gen_ft8")
    waveform = encoder.encode("k1abc ki5vnb em79", base_frequency_hz=1500)

    assert waveform.encoded.message == "K1ABC KI5VNB EM79"
    assert waveform.encoded.packed_payload == bytes(range(1, 11))
    assert len(waveform.encoded.tones) == FT8_CHANNEL_SYMBOLS
    assert waveform.sample_rate_hz == FT8_SAMPLE_RATE_HZ
    assert waveform.sample_count == FT8_SLOT_SAMPLES
    assert len(waveform.pcm_s16le) == FT8_SLOT_SAMPLES * 2
    assert calls == [[
        "/opt/ft8_lib/gen_ft8",
        "K1ABC KI5VNB EM79",
        calls[0][2],
        "1500",
    ]]
    assert "aplay" not in " ".join(calls[0])
    assert "arecord" not in " ".join(calls[0])


def test_ft8_lib_adapter_wraps_backend_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(
        argv: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=argv, returncode=2, stdout="Cannot parse message!", stderr=""
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(FT8EncoderError, match="exited 2"):
        Ft8LibEncoder("/opt/ft8_lib/gen_ft8").encode(
            "INVALID MESSAGE FORM", base_frequency_hz=1500
        )


def test_invalid_encoder_output_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(
        argv: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=argv, returncode=0, stdout="FSK tones: 0123", stderr=""
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(FT8EncoderError, match="packed payload"):
        Ft8LibEncoder("/opt/ft8_lib/gen_ft8").encode(
            "K1ABC KI5VNB EM79", base_frequency_hz=1500
        )


_PINNED_REFERENCE_VECTORS = (
    (
        "K1ABC KI5VNB EM79",
        "09bde354baee568847c8",
        "3140652032247523612626436605107432343140652117772401013222332703243147553140652",
        "6b4701d3e353f12b9927c6a254379d33baaeae1b2a2b2692d6f3c020f4f784b3",
    ),
    (
        "K1ABC KI5VNB -10",
        "09bde354baee569faa48",
        "3140652032247523612626436617463325173140652114252146701241357264504012473140652",
        "84a8853e2636c41c420372954340761cb743f34817439bfa4b140d0c1af2444e",
    ),
    (
        "K1ABC KI5VNB R-10",
        "09bde354baee56bfaa48",
        "3140652032247523612626436627463326563140652222516626577077002162670134673140652",
        "b0fcd4f7a5163f14c7a8ef4277d9f6a11fb7889f29a9651cd0b3c42556371461",
    ),
    (
        "K1ABC KI5VNB RRR",
        "09bde354baee569fa488",
        "3140652032247523612626436617455525013140652516660741025453700441605307253140652",
        "c8a077aaafe853da80fc03f283d8b9718892484d45bd9a936dee18d9389d0862",
    ),
    (
        "K1ABC KI5VNB RR73",
        "09bde354baee569fa4c8",
        "3140652032247523612626436617455433223140652146263166111674404703754264413140652",
        "2232c04332476af898a68343f10ac9e985e56cd6757ec844aafa7548414e8800",
    ),
    (
        "K1ABC KI5VNB 73",
        "09bde354baee569fa508",
        "3140652032247523612626436617456032013140652666262751357020763332321611543140652",
        "05bf11b382786a927ccf9ba4d82fa14773309fdb4aee22f78ceb6bd57bf0af55",
    ),
)


@pytest.mark.parametrize(
    ("message", "packed_hex", "tones_text", "pcm_sha256"),
    _PINNED_REFERENCE_VECTORS,
)
def test_pinned_ft8_lib_reference_vectors_when_available(
    message: str,
    packed_hex: str,
    tones_text: str,
    pcm_sha256: str,
) -> None:
    executable = os.environ.get("ROLLING_THUNDER_FT8_GEN_FT8")
    if not executable:
        pytest.skip("set ROLLING_THUNDER_FT8_GEN_FT8 for pinned backend vectors")

    waveform = Ft8LibEncoder(executable).encode(message, base_frequency_hz=1500)

    assert waveform.encoded.packed_payload.hex() == packed_hex
    assert "".join(str(tone) for tone in waveform.encoded.tones) == tones_text
    assert waveform.sample_count == FT8_SLOT_SAMPLES
    assert len(waveform.pcm_s16le) == 360_000
    assert hashlib.sha256(waveform.pcm_s16le).hexdigest() == pcm_sha256
