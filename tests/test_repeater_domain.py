"""Tests for typed six-meter repeater domain and stable identity."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from rolling_thunder.domain import Frequency
from rolling_thunder.repeater_domain import (
    RepeaterCatalog,
    RepeaterChannelType,
    RepeaterIdentity,
    RepeaterLocation,
    RepeaterRecord,
    RepeaterShiftDirection,
)


def repeater(
    name: str,
    rx_hz: int,
    tx_hz: int,
    *,
    active: bool = True,
) -> RepeaterRecord:
    rx = Frequency(hz=rx_hz)
    return RepeaterRecord(
        identity=RepeaterIdentity(name=name, rx_frequency=rx),
        name=name,
        callsign=name.split()[0],
        channel_type=RepeaterChannelType.ANALOGUE,
        rx_frequency=rx,
        tx_frequency=Frequency(hz=tx_hz),
        bandwidth_khz=Decimal(25),
        tx_tone_hz=Decimal("100.0"),
        location=RepeaterLocation(latitude=39.8, longitude=-84.0),
        source_active=active,
    )


def test_identity_is_stable_across_case_whitespace_and_row_order() -> None:
    first = repeater(" KI6SZ   Fairborn ", 51_660_000, 50_660_000)
    same = repeater("ki6sz fairborn", 51_660_000, 50_660_000)
    other = repeater("W8RRJ Columbus", 51_700_000, 50_700_000)

    assert first.stable_key == same.stable_key

    one = RepeaterCatalog.from_repeaters(
        source_filename="6m_repeaters.csv",
        source_sha256="a" * 64,
        repeaters=(other, first),
    )
    two = RepeaterCatalog.from_repeaters(
        source_filename="6m_repeaters.csv",
        source_sha256="a" * 64,
        repeaters=(first, other),
    )

    assert one.repeaters == two.repeaters
    assert [record.name for record in one.repeaters] == [
        "KI6SZ Fairborn",
        "W8RRJ Columbus",
    ]


def test_duplicate_stable_identity_is_rejected() -> None:
    first = repeater("KI6SZ Fairborn", 51_660_000, 50_660_000)
    duplicate = repeater("ki6sz fairborn", 51_660_000, 50_660_000)

    with pytest.raises(ValueError, match="stable identities must be unique"):
        RepeaterCatalog.from_repeaters(
            source_filename="6m_repeaters.csv",
            source_sha256="b" * 64,
            repeaters=(first, duplicate),
        )


def test_shift_direction_and_offset_are_derived_exactly() -> None:
    minus = repeater("K1MINUS Test", 52_000_000, 51_000_000)
    plus = repeater("K1PLUS Test", 52_000_000, 53_000_000)
    simplex = repeater("K1SIMPLEX Test", 52_000_000, 52_000_000)

    assert minus.shift_direction is RepeaterShiftDirection.MINUS
    assert minus.offset_hz == 1_000_000
    assert plus.shift_direction is RepeaterShiftDirection.PLUS
    assert plus.offset_hz == 1_000_000
    assert simplex.shift_direction is RepeaterShiftDirection.SIMPLEX
    assert simplex.offset_hz == 0


def test_record_rejects_frequency_outside_six_meter_band() -> None:
    rx = Frequency(hz=51_660_000)

    with pytest.raises(ValidationError, match="TX frequency must be in the 6 m band"):
        RepeaterRecord(
            identity=RepeaterIdentity(name="KI6SZ Fairborn", rx_frequency=rx),
            name="KI6SZ Fairborn",
            callsign="KI6SZ",
            channel_type=RepeaterChannelType.ANALOGUE,
            rx_frequency=rx,
            tx_frequency=Frequency(hz=144_000_000),
            bandwidth_khz=Decimal(25),
            location=RepeaterLocation(latitude=39.8, longitude=-84.0),
            source_active=True,
        )
