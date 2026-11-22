"""Verify the memory-only WSPR decoder boundary and native WSPR-2 fixture."""

from array import array
from math import sin, tau
from pathlib import Path
from random import Random
from sys import byteorder
from threading import Event, Timer

import pytest

from rolling_thunder.wspr_decoder import (
    WSPR_PCM_BYTES,
    WSPR_SAMPLE_RATE_HZ,
    PipeWsprDecoder,
    WsprDecode,
    WsprDecoderError,
    _decode_spots,
)

_DIAL_HZ = 10_138_700


def test_decode_spots_handles_compound_callsigns_and_unusable_locators() -> None:
    output = (
        b"-18 1.0 10140200 -1 K1JT FN20 30\n"
        b"-22 -0.2 10140201 0 <PA0SKT/2> JO33ab 37\n"
        b"-23 0.0 10140202 1 K1JT/P 37\n"
        b"-25 0.0 10140203 0 W5BIT ZZ09 37\n"
        b"-22 0.0 10145000 0 K1JT FN20 30\n"
        b"-22 0.0 10140204 0 <...> JO33ab 37\n"
        b"corrupt or escaped output\n"
        b"<DecodeFinished>\n"
    )

    assert _decode_spots(output, _DIAL_HZ) == (
        WsprDecode("K1JT", "FN20", 10_140_200, -18, 1.0, -1, 30),
        WsprDecode("PA0SKT/2", "JO33AB", 10_140_201, -22, -0.2, 0, 37),
        WsprDecode("K1JT/P", None, 10_140_202, -23, 0.0, 1, 37),
        WsprDecode("W5BIT", None, 10_140_203, -25, 0.0, 0, 37),
    )


def test_incomplete_window_and_interrupted_decoder_output_are_rejected() -> None:
    with pytest.raises(WsprDecoderError, match="window is incomplete"):
        PipeWsprDecoder().decode(b"\x00", _DIAL_HZ, Event())
    with pytest.raises(WsprDecoderError, match="Incomplete WSPR decoder output"):
        _decode_spots(b"-18 1.0 10140200 -1 K1JT FN20 30\n", _DIAL_HZ)
    with pytest.raises(WsprDecoderError, match="Invalid WSPR decoder output"):
        _decode_spots(b"\x00" * 4097, _DIAL_HZ)


def test_decoder_deadline_and_cancellation_stop_a_stalled_process(tmp_path: Path) -> None:
    executable = tmp_path / "stalled-decoder"
    executable.write_text("#!/bin/sh\nexec sleep 60\n")
    executable.chmod(0o700)
    pcm = bytes(WSPR_PCM_BYTES)

    with pytest.raises(WsprDecoderError, match="timed out"):
        PipeWsprDecoder(str(executable), timeout_s=0.15).decode(pcm, _DIAL_HZ, Event())

    cancel = Event()
    timer = Timer(0.05, cancel.set)
    timer.start()
    try:
        assert PipeWsprDecoder(str(executable), timeout_s=1.0).decode(pcm, _DIAL_HZ, cancel) == ()
    finally:
        timer.cancel()
        timer.join()


def test_native_decoder_reads_through_pipes_without_spool_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decoder = PipeWsprDecoder()
    if not decoder.available:
        pytest.skip("The optional Linux FFTW decoder was not built.")
    monkeypatch.chdir(tmp_path)

    # Standard Type 1 encoder symbols for K1JT FN20 37. Produce one baseband
    # frame in memory with continuous phase and a deterministic noise floor.
    symbols = (
        "332222201022331222320303131000200212032122200232112233010001103220013232301012012"
        "012110001103232223020201003223112132211232223132020032322310222200130123100233222"
    )
    samples_per_symbol = 8192
    random = Random(2026)
    sample_count = WSPR_PCM_BYTES // 2
    pcm = array("h", (random.randrange(-80, 81) for _ in range(sample_count)))
    phase = 0.0
    index = WSPR_SAMPLE_RATE_HZ
    for symbol in symbols:
        freq = 1500.0 + int(symbol) * WSPR_SAMPLE_RATE_HZ / samples_per_symbol
        increment = tau * freq / WSPR_SAMPLE_RATE_HZ
        for _ in range(samples_per_symbol):
            pcm[index] += round(1800 * sin(phase))
            phase = (phase + increment) % tau
            index += 1
    if byteorder != "little":
        pcm.byteswap()

    decoded = decoder.decode(pcm.tobytes(), _DIAL_HZ, Event())
    assert len(decoded) == 1
    spot = decoded[0]
    assert (spot.callsign, spot.locator, spot.power_dbm) == ("K1JT", "FN20", 37)
    assert abs(spot.frequency_hz - (_DIAL_HZ + 1502)) <= 1
    assert not list(tmp_path.iterdir())
