"""Tests for current-GPS six-meter repeater distance filtering."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from rolling_thunder.domain import Frequency, GPSFixState, GPSPosition
from rolling_thunder.gps import GPSConnectionState, GPSState
from rolling_thunder.repeater_domain import (
    RepeaterCatalog,
    RepeaterChannelType,
    RepeaterIdentity,
    RepeaterLocation,
    RepeaterRecord,
)
from rolling_thunder.repeater_nearby import (
    NearbyRepeaterStateKind,
    RepeaterNearbyService,
    haversine_distance_miles,
)

NOW = datetime(2026, 8, 9, 20, 30, tzinfo=UTC)


def repeater(name: str, longitude: float, *, active: bool = True) -> RepeaterRecord:
    rx = Frequency(hz=52_000_000)
    return RepeaterRecord(
        identity=RepeaterIdentity(name=name, rx_frequency=rx),
        name=name,
        callsign=name.split()[0],
        channel_type=RepeaterChannelType.ANALOGUE,
        rx_frequency=rx,
        tx_frequency=Frequency(hz=51_000_000),
        bandwidth_khz=Decimal("25"),
        location=RepeaterLocation(latitude=0.0, longitude=longitude),
        source_active=active,
    )


def catalog(*records: RepeaterRecord) -> RepeaterCatalog:
    return RepeaterCatalog.from_repeaters(
        source_filename="6m_repeaters.csv",
        source_sha256="c" * 64,
        repeaters=records,
    )


def gps_state(*, fix_time: datetime = NOW) -> GPSState:
    position = GPSPosition(
        fix_state=GPSFixState.THREE_DIMENSIONAL,
        latitude=0.0,
        longitude=0.0,
        updated_at=fix_time,
    )
    return GPSState(
        connection_state=GPSConnectionState.CONNECTED,
        position=position,
        updated_at=fix_time,
    )


def test_haversine_known_one_degree_equator_distance() -> None:
    assert haversine_distance_miles(0.0, 0.0, 0.0, 1.0) == pytest.approx(
        69.0934,
        abs=0.01,
    )


def test_fifty_mile_filter_is_inclusive_and_excludes_just_outside() -> None:
    inside = repeater("K1IN Test", 0.72)
    outside = repeater("K1OUT Test", 0.73)
    service = RepeaterNearbyService(
        catalog(inside, outside),
        clock=lambda: NOW,
    )

    state = service.nearby(gps_state())

    assert state.kind is NearbyRepeaterStateKind.READY
    assert [item.repeater.name for item in state.repeaters] == ["K1IN Test"]
    assert state.repeaters[0].distance_miles < 50.0
    assert haversine_distance_miles(0.0, 0.0, 0.0, 0.73) > 50.0


def test_nearby_order_is_distance_then_frequency_then_stable_identity() -> None:
    farther = repeater("K1FAR Test", 0.50)
    alpha = repeater("K1AAA Test", 0.25)
    bravo = repeater("K1BBB Test", 0.25)
    service = RepeaterNearbyService(
        catalog(farther, bravo, alpha),
        clock=lambda: NOW,
    )

    state = service.nearby(gps_state())

    assert [item.repeater.name for item in state.repeaters] == [
        "K1AAA Test",
        "K1BBB Test",
        "K1FAR Test",
    ]


def test_effective_active_uses_override_without_mutating_source_default() -> None:
    record = repeater("K1ABC Test", 0.25, active=True)
    service = RepeaterNearbyService(
        catalog(record),
        overrides={record.stable_key: False},
        clock=lambda: NOW,
    )

    state = service.nearby(gps_state())

    assert state.repeaters[0].effective_active is False
    assert record.source_active is True


def test_missing_fix_produces_explicit_unavailable_state() -> None:
    state = GPSState(
        connection_state=GPSConnectionState.CONNECTED,
        position=GPSPosition(
            fix_state=GPSFixState.NO_FIX,
            updated_at=NOW,
        ),
        updated_at=NOW,
    )
    service = RepeaterNearbyService(catalog(), clock=lambda: NOW)

    nearby = service.nearby(state)

    assert nearby.kind is NearbyRepeaterStateKind.GPS_UNAVAILABLE
    assert nearby.repeaters == ()
    assert "UNAVAILABLE" in nearby.detail


def test_stale_fix_produces_explicit_stale_state_without_guessing_distance() -> None:
    service = RepeaterNearbyService(
        catalog(repeater("K1ABC Test", 0.25)),
        gps_stale_after=timedelta(seconds=10),
        clock=lambda: NOW,
    )

    state = service.nearby(gps_state(fix_time=NOW - timedelta(seconds=11)))

    assert state.kind is NearbyRepeaterStateKind.GPS_STALE
    assert state.repeaters == ()
    assert state.gps_fix_time == NOW - timedelta(seconds=11)


def test_future_fix_is_treated_as_current_like_existing_live_map_policy() -> None:
    service = RepeaterNearbyService(catalog(), clock=lambda: NOW)

    state = service.nearby(gps_state(fix_time=NOW + timedelta(seconds=1)))

    assert state.kind is NearbyRepeaterStateKind.READY


def test_naive_clock_is_rejected() -> None:
    service = RepeaterNearbyService(
        catalog(),
        clock=lambda: NOW.replace(tzinfo=None),
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        service.nearby(gps_state())
