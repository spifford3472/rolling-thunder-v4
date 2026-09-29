"""Tests for deterministic FT8 timing and UTC period identity."""

from datetime import UTC, datetime, timedelta

import pytest

from rolling_thunder.ft8.domain import FT8Period, FT8PeriodParity
from rolling_thunder.ft8.timing import FakeFT8Clock


def test_utc_maps_to_15_second_period_boundaries() -> None:
    epoch = datetime(1970, 1, 1, tzinfo=UTC)

    assert FT8Period.from_utc(epoch + timedelta(seconds=14.999999)).index == 0
    assert FT8Period.from_utc(epoch + timedelta(seconds=15)).index == 1
    assert FT8Period.from_utc(epoch + timedelta(seconds=29.999999)).index == 1
    assert FT8Period.from_utc(epoch + timedelta(seconds=30)).index == 2
    assert FT8Period.from_utc(epoch + timedelta(seconds=30)).parity is FT8PeriodParity.EVEN


def test_fake_clock_advances_utc_monotonic_and_period_without_sleep() -> None:
    clock = FakeFT8Clock(datetime(1970, 1, 1, tzinfo=UTC), monotonic_seconds=10.0)

    clock.advance(15.25)

    assert clock.now_utc() == datetime(1970, 1, 1, 0, 0, 15, 250000, tzinfo=UTC)
    assert clock.monotonic() == 25.25
    assert clock.current_period() == FT8Period(index=1)


def test_fake_clock_refuses_backward_time() -> None:
    clock = FakeFT8Clock(datetime(1970, 1, 1, tzinfo=UTC))

    with pytest.raises(ValueError, match="backward"):
        clock.advance(-1)
