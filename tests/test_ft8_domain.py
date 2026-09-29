"""Tests for immutable project-owned FT8 domain models."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from rolling_thunder.ft8.domain import (
    FT8Decode,
    FT8MessageKind,
    FT8Period,
    FT8PeriodParity,
    FT8QsoContext,
)


def test_period_exposes_stable_start_and_parity() -> None:
    period = FT8Period(index=100)

    assert period.start_utc == datetime.fromtimestamp(1500, tz=UTC)
    assert period.parity is FT8PeriodParity.EVEN
    assert FT8Period(index=101).parity is FT8PeriodParity.ODD


def test_decode_normalizes_callsign_grid_and_metadata_is_immutable() -> None:
    decode = FT8Decode(
        period=FT8Period(index=100),
        snr_db=-12,
        dt_seconds=0.2,
        audio_frequency_hz=1500,
        raw_message=" CQ k1abc em79xm ",
        kind=FT8MessageKind.CQ,
        source_callsign="k1abc",
        grid="em79XM",
        backend_metadata={"decoder": "synthetic"},
    )

    assert decode.source_callsign == "K1ABC"
    assert decode.grid == "EM79xm"
    assert decode.raw_message == "CQ k1abc em79xm"
    with pytest.raises(TypeError):
        decode.backend_metadata["decoder"] = "changed"  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        decode.snr_db = -5  # type: ignore[misc]


def test_qso_context_is_frozen_snapshot() -> None:
    source = {"grid": "EM79xm", "latitude": 39.5, "longitude": -84.1}
    context = FT8QsoContext(
        local_callsign="ki5vnb",
        remote_callsign="k1abc",
        target_audio_frequency_hz=1500,
        radio_frequency_hz=14_074_000,
        radio_band="20m",
        radio_mode="DIG-U",
        local_grid=source["grid"],
        latitude=source["latitude"],
        longitude=source["longitude"],
        location_label="mobile",
        tx_parity=FT8PeriodParity.ODD,
        authorized_period=FT8Period(index=100),
        authorized_utc=datetime.fromtimestamp(1501, tz=UTC),
    )
    source.update({"grid": "EM89aa", "latitude": 40.0, "longitude": -83.0})

    assert context.local_callsign == "KI5VNB"
    assert context.remote_callsign == "K1ABC"
    assert context.local_grid == "EM79xm"
    assert context.latitude == 39.5
    assert context.longitude == -84.1
    with pytest.raises(FrozenInstanceError):
        context.local_grid = "EM89aa"  # type: ignore[misc]


def test_invalid_decode_values_are_rejected() -> None:
    with pytest.raises(ValueError, match="audio_frequency_hz"):
        FT8Decode(
            period=FT8Period(index=100),
            snr_db=-10,
            dt_seconds=0.0,
            audio_frequency_hz=0,
            raw_message="CQ K1ABC EM79",
            kind=FT8MessageKind.CQ,
            source_callsign="K1ABC",
        )
