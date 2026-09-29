"""Tests for the receive-only Checkpoint 3 FT8 decoder boundary."""

import subprocess
import wave
from pathlib import Path

import pytest

from rolling_thunder.ft8.decoder import (
    FT8DecoderError,
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
        samples=(0, 100, -100, 0),
    )


@pytest.mark.parametrize(
    ("message", "kind", "source", "destination", "grid", "report", "qualifier"),
    [
        ("CQ K1ABC EM79", FT8MessageKind.CQ, "K1ABC", None, "EM79", None, None),
        ("CQ DX K1ABC EM79", FT8MessageKind.CQ, "K1ABC", None, "EM79", None, "DX"),
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
        "094445 -10 0.3 601 THIS IS UNSUPPORTED",
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
    assert pcm.samples == (0, 1)


def test_pcm_contract_rejects_out_of_range_samples() -> None:
    with pytest.raises(ValueError, match="signed 16-bit"):
        FT8PcmPeriod(
            period=FT8Period(index=100),
            sample_rate_hz=12_000,
            samples=(40_000,),
        )
