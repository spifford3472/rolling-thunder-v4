"""Tests for pure live-map GPS presentation state."""

from datetime import UTC, datetime, timedelta

import pytest

from rolling_thunder.domain import GPSFixState, GPSPosition
from rolling_thunder.gps import GPSConnectionState, GPSState
from rolling_thunder.live_map import GeoPoint, LiveMapController, LiveMapGpsStatus

NOW = datetime(2026, 8, 2, 20, 0, tzinfo=UTC)
NAIVE_NOW = NOW.replace(tzinfo=None)


def gps_state(
    *,
    connection: GPSConnectionState = GPSConnectionState.CONNECTED,
    fix: GPSFixState = GPSFixState.THREE_DIMENSIONAL,
    latitude: float | None = 39.53,
    longitude: float | None = -84.08,
    fix_time: datetime = NOW,
    speed_m_s: float | None = None,
    heading_degrees: float | None = None,
    error: str | None = None,
) -> GPSState:
    position = None
    if connection is GPSConnectionState.CONNECTED:
        position = GPSPosition(
            fix_state=fix,
            latitude=latitude,
            longitude=longitude,
            speed_m_s=speed_m_s,
            heading_degrees=heading_degrees,
            updated_at=fix_time,
        )
    return GPSState(
        connection_state=connection,
        position=position,
        updated_at=NOW,
        last_error=error,
    )


def test_geo_point_rejects_out_of_range_coordinates() -> None:
    with pytest.raises(ValueError, match="Latitude"):
        GeoPoint(91, 0)
    with pytest.raises(ValueError, match="Longitude"):
        GeoPoint(0, 181)


def test_controller_waits_without_a_valid_fix() -> None:
    controller = LiveMapController(clock=lambda: NOW)

    state = controller.update(
        gps_state(
            fix=GPSFixState.NO_FIX,
            latitude=None,
            longitude=None,
        )
    )

    assert state.status is LiveMapGpsStatus.WAITING
    assert state.position is None
    assert state.grid is None
    assert state.detail == "WAITING FOR GPS FIX"
    assert state.is_current is False


def test_controller_presents_a_fresh_fix_as_current() -> None:
    controller = LiveMapController(clock=lambda: NOW)

    state = controller.update(gps_state())

    assert state.status is LiveMapGpsStatus.READY
    assert state.position == GeoPoint(39.53, -84.08)
    assert state.grid == "EM79xm"
    assert state.detail == "GPS READY"
    assert state.fix_time == NOW
    assert state.is_current is True


def test_controller_marks_old_connected_fix_stale() -> None:
    controller = LiveMapController(
        stale_after=timedelta(seconds=10),
        clock=lambda: NOW,
    )

    state = controller.update(gps_state(fix_time=NOW - timedelta(seconds=14)))

    assert state.status is LiveMapGpsStatus.STALE
    assert state.detail == "GPS STALE — LAST FIX 14 SECONDS AGO"
    assert state.position == GeoPoint(39.53, -84.08)
    assert state.is_current is False


@pytest.mark.parametrize(
    ("connection", "error", "expected_detail"),
    [
        (
            GPSConnectionState.DISCONNECTED,
            None,
            "GPS DISCONNECTED — LAST KNOWN POSITION",
        ),
        (
            GPSConnectionState.ERROR,
            "serial failed",
            "GPS ERROR — LAST KNOWN POSITION",
        ),
    ],
)
def test_controller_retains_last_valid_position_after_loss(
    connection: GPSConnectionState,
    error: str | None,
    expected_detail: str,
) -> None:
    controller = LiveMapController(clock=lambda: NOW)
    controller.update(gps_state())

    state = controller.update(
        gps_state(
            connection=connection,
            latitude=None,
            longitude=None,
            error=error,
        )
    )

    assert state.status is LiveMapGpsStatus.LAST_KNOWN
    assert state.position == GeoPoint(39.53, -84.08)
    assert state.detail == expected_detail
    assert state.is_current is False


def test_controller_does_not_claim_a_position_for_startup_error() -> None:
    controller = LiveMapController(clock=lambda: NOW)

    state = controller.update(
        gps_state(
            connection=GPSConnectionState.ERROR,
            latitude=None,
            longitude=None,
            error="serial failed",
        )
    )

    assert state.status is LiveMapGpsStatus.ERROR
    assert state.position is None
    assert state.detail == "GPS ERROR — POSITION UNAVAILABLE"


def test_controller_reacquires_after_last_known_state() -> None:
    controller = LiveMapController(clock=lambda: NOW)
    controller.update(gps_state())
    controller.update(
        gps_state(
            connection=GPSConnectionState.DISCONNECTED,
            latitude=None,
            longitude=None,
        )
    )

    state = controller.update(gps_state(latitude=39.60, longitude=-84.10, fix_time=NOW))

    assert state.status is LiveMapGpsStatus.READY
    assert state.position == GeoPoint(39.60, -84.10)
    assert state.is_current is True


def test_controller_uses_heading_while_vehicle_is_moving() -> None:
    controller = LiveMapController(clock=lambda: NOW)

    state = controller.update(gps_state(speed_m_s=5.0, heading_degrees=123.0))

    assert state.heading_degrees == pytest.approx(123.0)


def test_controller_retains_last_reliable_heading_while_stopped() -> None:
    controller = LiveMapController(clock=lambda: NOW)
    controller.update(gps_state(speed_m_s=4.0, heading_degrees=270.0))

    state = controller.update(gps_state(speed_m_s=0.2, heading_degrees=45.0))

    assert state.heading_degrees == pytest.approx(270.0)


def test_controller_has_no_heading_before_reliable_movement() -> None:
    controller = LiveMapController(clock=lambda: NOW)

    state = controller.update(gps_state(speed_m_s=0.1, heading_degrees=180.0))

    assert state.heading_degrees is None


def test_controller_rejects_negative_heading_speed_threshold() -> None:
    with pytest.raises(ValueError, match="heading speed"):
        LiveMapController(minimum_heading_speed_m_s=-0.1)


def test_controller_rejects_naive_clock() -> None:
    controller = LiveMapController(clock=lambda: NAIVE_NOW)

    with pytest.raises(ValueError, match="timezone-aware"):
        controller.update(None)


@pytest.mark.parametrize(
    ("age_seconds", "expected"),
    [
        (0, True),
        (59, True),
        (60, True),
        (61, False),
    ],
)
def test_pota_position_grace_uses_age_of_last_valid_fix(
    age_seconds: int,
    expected: bool,
) -> None:
    controller = LiveMapController(clock=lambda: NOW)
    presentation = controller.update(
        gps_state(fix_time=NOW - timedelta(seconds=age_seconds))
    )

    assert controller.pota_position_is_recent(
        presentation,
        grace_after=timedelta(seconds=60),
    ) is expected


def test_pota_position_grace_retains_last_fix_during_brief_disconnect() -> None:
    controller = LiveMapController(clock=lambda: NOW)
    controller.update(gps_state(fix_time=NOW - timedelta(seconds=30)))
    presentation = controller.update(
        gps_state(
            connection=GPSConnectionState.DISCONNECTED,
            latitude=None,
            longitude=None,
        )
    )

    assert controller.pota_position_is_recent(
        presentation,
        grace_after=timedelta(seconds=60),
    ) is True
