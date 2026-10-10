"""Tests for the receive-only Checkpoint 3 FT8 decoder boundary."""

import subprocess
import wave
from pathlib import Path

import pytest

from rolling_thunder.ft8.decoder import (
    ComparingFT8Decoder,
    FT8DecoderDiagnostics,
    FT8DecoderError,
    FT8DecoderResult,
    Ft8LibDecoder,
    Ft8monDecoder,
    FT8PcmPeriod,
    parse_ft8_message,
)
from rolling_thunder.ft8.domain import FT8MessageKind, FT8Period


def _pcm() -> FT8PcmPeriod:
    return FT8PcmPeriod(
        period=FT8Period(index=100),
        sample_rate_hz=12_000,
        pcm_s16le=bytes((0, 0, 100, 0, 156, 255, 0, 0)),
    )


@pytest.mark.parametrize(
    ("message", "kind", "source", "destination", "grid", "report", "qualifier"),
    [
        ("CQ K1ABC EM79", FT8MessageKind.CQ, "K1ABC", None, "EM79", None, None),
        ("CQ DX K1ABC EM79", FT8MessageKind.CQ, "K1ABC", None, "EM79", None, "DX"),
        (
            "KI5VNB W4YRL EL99",
            FT8MessageKind.ADDRESSED_GRID,
            "W4YRL",
            "KI5VNB",
            "EL99",
            None,
            None,
        ),
        ("W1AW K1ABC -10", FT8MessageKind.REPORT, "K1ABC", "W1AW", None, -10, None),
        ("W1AW K1ABC R-07", FT8MessageKind.R_REPORT, "K1ABC", "W1AW", None, -7, None),
        ("W1AW K1ABC RR73", FT8MessageKind.ACK_73, "K1ABC", "W1AW", None, None, None),
        ("HELLO WORLD", FT8MessageKind.OTHER, None, None, None, None, None),
    ],
)
def test_message_normalization(
    message: str,
    kind: FT8MessageKind,
    source: str | None,
    destination: str | None,
    grid: str | None,
    report: int | None,
    qualifier: str | None,
) -> None:
    parsed = parse_ft8_message(message)

    assert parsed.kind is kind
    assert parsed.source_callsign == source
    assert parsed.destination_callsign == destination
    assert parsed.grid == grid
    assert parsed.report_db == report
    assert parsed.cq_qualifier == qualifier


def test_ft8mon_output_normalizes_into_project_decode() -> None:
    decoder = Ft8monDecoder("ft8mon")
    decode = decoder._parse_line(
        "094445 -19 147 0.00 820.4 CQ DX WD6DBM CM97",
        period=FT8Period(index=100),
    )

    assert decode is not None
    assert decode.period == FT8Period(index=100)
    assert decode.snr_db == -19
    assert decode.dt_seconds == 0.0
    assert decode.audio_frequency_hz == 820
    assert decode.raw_message == "CQ DX WD6DBM CM97"
    assert decode.kind is FT8MessageKind.CQ
    assert decode.source_callsign == "WD6DBM"
    assert decode.grid == "CM97"
    assert decode.cq_qualifier == "DX"
    assert decode.backend_metadata["decoder"] == "ft8mon"
    assert decode.backend_metadata["correct_bits"] == "147"


def test_ft8_lib_output_normalizes_required_metrics() -> None:
    decoder = Ft8LibDecoder("decode_ft8")
    decode = decoder._parse_line(
        "000000 +12.5 +0.25 1000 ~  CQ K1ABC EM79",
        period=FT8Period(index=101),
    )

    assert decode is not None
    assert decode.period == FT8Period(index=101)
    assert decode.period.parity.value == "odd"
    assert decode.snr_db == 12
    assert decode.dt_seconds == 0.25
    assert decode.audio_frequency_hz == 1000
    assert decode.kind is FT8MessageKind.CQ
    assert decode.source_callsign == "K1ABC"
    assert decode.backend_metadata["decoder"] == "kgoba/ft8_lib"
    assert decode.backend_metadata["raw_snr"] == "+12.5"


def test_ft8_lib_parser_accepts_observed_output_without_optional_tilde() -> None:
    decode = Ft8LibDecoder("decode_ft8")._parse_line(
        "  000000 -18 -.25 742.5 CQ W1AW FN31  ",
        period=FT8Period(index=101),
    )

    assert decode is not None
    assert decode.raw_message == "CQ W1AW FN31"
    assert decode.audio_frequency_hz == 742
    assert decode.dt_seconds == -0.25


def test_malformed_backend_line_is_ignored() -> None:
    assert (
        Ft8monDecoder("ft8mon")._parse_line(
            "not decoder output",
            period=FT8Period(index=100),
        )
        is None
    )


def test_partially_supported_message_is_retained_as_other() -> None:
    decoder = Ft8monDecoder("ft8mon")
    decode = decoder._parse_line(
        "094445 -10 147 0.30 601.0 THIS IS UNSUPPORTED",
        period=FT8Period(index=100),
    )

    assert decode is not None
    assert decode.kind is FT8MessageKind.OTHER
    assert decode.raw_message == "THIS IS UNSUPPORTED"


def test_decoder_failure_is_wrapped_safely(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["ft8mon"],
            returncode=2,
            stdout="",
            stderr="bad wav",
        )

    monkeypatch.setattr(subprocess, "run", fail)

    with pytest.raises(FT8DecoderError, match="exited 2"):
        Ft8monDecoder("ft8mon").decode(_pcm())


def test_decoder_timeout_is_wrapped_safely(monkeypatch: pytest.MonkeyPatch) -> None:
    def timeout(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd=["ft8mon"], timeout=1.0)

    monkeypatch.setattr(subprocess, "run", timeout)

    with pytest.raises(FT8DecoderError, match="timed out"):
        Ft8monDecoder("ft8mon", timeout_s=1.0).decode(_pcm())


def test_wav_loader_requires_mono_16_bit_pcm(tmp_path: Path) -> None:
    path = tmp_path / "reference.wav"
    with wave.open(str(path), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(12_000)
        target.writeframes(bytes((0, 0, 1, 0)))

    pcm = FT8PcmPeriod.from_wav(path, period=FT8Period(index=102))

    assert pcm.period == FT8Period(index=102)
    assert pcm.sample_rate_hz == 12_000
    assert pcm.pcm_s16le == bytes((0, 0, 1, 0))


def test_pcm_contract_rejects_partial_sample_bytes() -> None:
    with pytest.raises(ValueError, match="complete signed 16-bit samples"):
        FT8PcmPeriod(
            period=FT8Period(index=100),
            sample_rate_hz=12_000,
            pcm_s16le=b"\x00",
        )


class RecordingDiagnosticDecoder:
    def __init__(self, backend: str, count: int) -> None:
        self.backend = backend
        self.count = count
        self.pcm_ids: list[int] = []

    def decode_with_diagnostics(self, pcm: FT8PcmPeriod) -> FT8DecoderResult:
        self.pcm_ids.append(id(pcm))
        diagnostics = FT8DecoderDiagnostics(
            backend=self.backend,
            runtime_seconds=0.1,
            raw_line_count=self.count,
            parsed_decode_count=self.count,
            cq_decode_count=0,
            malformed_line_count=0,
        )
        return FT8DecoderResult(decodes=(), primary=diagnostics)


def test_comparison_decoder_uses_the_exact_same_pcm_for_both_backends() -> None:
    primary = RecordingDiagnosticDecoder("ft8_lib", 2)
    comparison = RecordingDiagnosticDecoder("ft8mon", 3)
    pcm = _pcm()

    result = ComparingFT8Decoder(primary, comparison).decode_with_diagnostics(pcm)

    assert primary.pcm_ids == [id(pcm)]
    assert comparison.pcm_ids == [id(pcm)]
    assert result.primary.parsed_decode_count == 2
    assert result.comparison is not None
    assert result.comparison.parsed_decode_count == 3


def test_comparison_decoder_stops_secondary_work_after_session_cutoff() -> None:
    primary = RecordingDiagnosticDecoder("ft8_lib", 2)
    comparison = RecordingDiagnosticDecoder("ft8mon", 3)
    enabled = False

    result = ComparingFT8Decoder(
        primary,
        comparison,
        comparison_enabled=lambda: enabled,
    ).decode_with_diagnostics(_pcm())

    assert result.primary.parsed_decode_count == 2
    assert result.comparison is None
    assert comparison.pcm_ids == []
