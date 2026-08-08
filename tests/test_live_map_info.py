"""Tests for pure live-map information and subsystem health."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from rolling_thunder.live_map import GeoPoint, LiveMapGpsStatus, LiveMapPresentation
from rolling_thunder.live_map_info import LiveMapHealthLevel, LiveMapInfoController
from rolling_thunder.live_map_service import LiveMapSnapshot, MapDataStatus

NOW = datetime(2026, 8, 8, 19, 11, tzinfo=UTC)
LOCAL_NOW = NOW.astimezone(timezone(timedelta(hours=-4)))


def presentation(
    *,
    status: LiveMapGpsStatus = LiveMapGpsStatus.READY,
    fix_time: datetime | None = NOW,
    grid: str | None = "EM79xm",
) -> LiveMapPresentation:
    position = None
    if fix_time is not None:
        position = GeoPoint(39.53, -84.08)
    return LiveMapPresentation(
        status=status,
        position=position,
        grid=grid,
        detail=status.value,
        fix_time=fix_time,
        is_current=(status is LiveMapGpsStatus.READY),
    )


def snapshot(
    status: MapDataStatus,
    *,
    updated_at: datetime = NOW,
) -> LiveMapSnapshot:
    return LiveMapSnapshot(
        status=status,
        viewport=None,
        tiles=(),
        detail=status.value,
        updated_at=updated_at,
    )


def test_information_box_formats_local_utc_grid_and_temperature_placeholder() -> None:
    controller = LiveMapInfoController(clock=lambda: LOCAL_NOW)

    state = controller.update(
        presentation(),
        snapshot(MapDataStatus.READY),
    )

    assert state.local_time == "3:11 PM"
    assert state.utc_time == "19:11 UTC"
    assert state.grid == "EM79XM"
    assert state.temperature_f == "--°F"
    assert state.temperature_c == "--°C"
    assert state.temperature_detail == "UNAVAILABLE"


def test_ready_gps_and_ready_map_are_healthy() -> None:
    controller = LiveMapInfoController(clock=lambda: NOW)

    state = controller.update(
        presentation(),
        snapshot(MapDataStatus.READY),
    )

    assert state.gps_health.level is LiveMapHealthLevel.HEALTHY
    assert state.gps_health.detail == "READY"
    assert state.map_health.level is LiveMapHealthLevel.HEALTHY
    assert state.map_health.detail == "READY"


def test_complete_offline_cache_is_healthy_not_a_network_failure() -> None:
    controller = LiveMapInfoController(clock=lambda: NOW)

    state = controller.update(
        presentation(),
        snapshot(MapDataStatus.CACHE_ONLY),
    )

    assert state.map_health.level is LiveMapHealthLevel.HEALTHY
    assert state.map_health.detail == "OFFLINE CACHE"


def test_recent_map_loss_is_degraded_and_retains_last_usable_timestamp() -> None:
    current = [NOW]
    controller = LiveMapInfoController(clock=lambda: current[0])
    controller.update(presentation(), snapshot(MapDataStatus.READY, updated_at=NOW))

    current[0] = NOW + timedelta(seconds=20)
    state = controller.update(
        presentation(fix_time=current[0]),
        snapshot(MapDataStatus.UNAVAILABLE, updated_at=current[0]),
    )

    assert state.map_health.level is LiveMapHealthLevel.DEGRADED
    assert state.map_health.detail == "UNAVAILABLE"
    assert state.map_health.last_usable_at == NOW
    assert state.map_health.age == timedelta(seconds=20)


def test_map_loss_becomes_unavailable_at_thirty_seconds() -> None:
    current = [NOW]
    controller = LiveMapInfoController(clock=lambda: current[0])
    controller.update(presentation(), snapshot(MapDataStatus.READY, updated_at=NOW))

    current[0] = NOW + timedelta(seconds=30)
    state = controller.update(
        presentation(fix_time=current[0]),
        snapshot(MapDataStatus.UNAVAILABLE, updated_at=current[0]),
    )

    assert state.map_health.level is LiveMapHealthLevel.UNAVAILABLE
    assert state.map_health.last_usable_at == NOW
    assert state.map_health.age == timedelta(seconds=30)


def test_recent_stale_gps_is_degraded_then_becomes_unavailable() -> None:
    current = [NOW + timedelta(seconds=20)]
    controller = LiveMapInfoController(clock=lambda: current[0])

    recent = controller.update(
        presentation(
            status=LiveMapGpsStatus.STALE,
            fix_time=NOW,
        ),
        snapshot(MapDataStatus.READY, updated_at=current[0]),
    )

    assert recent.gps_health.level is LiveMapHealthLevel.DEGRADED
    assert recent.gps_health.age == timedelta(seconds=20)

    current[0] = NOW + timedelta(seconds=30)
    unavailable = controller.update(
        presentation(
            status=LiveMapGpsStatus.LAST_KNOWN,
            fix_time=NOW,
        ),
        snapshot(MapDataStatus.READY, updated_at=current[0]),
    )

    assert unavailable.gps_health.level is LiveMapHealthLevel.UNAVAILABLE
    assert unavailable.gps_health.age == timedelta(seconds=30)


def test_never_usable_subsystems_start_unavailable() -> None:
    controller = LiveMapInfoController(clock=lambda: NOW)

    state = controller.update(
        presentation(
            status=LiveMapGpsStatus.WAITING,
            fix_time=None,
            grid=None,
        ),
        None,
    )

    assert state.grid == "------"
    assert state.gps_health.level is LiveMapHealthLevel.UNAVAILABLE
    assert state.gps_health.last_usable_at is None
    assert state.map_health.level is LiveMapHealthLevel.UNAVAILABLE
    assert state.map_health.last_usable_at is None


def test_controller_rejects_nonpositive_unavailable_threshold() -> None:
    with pytest.raises(ValueError, match="threshold"):
        LiveMapInfoController(unavailable_after=timedelta(0))


def test_controller_rejects_naive_clock() -> None:
    controller = LiveMapInfoController(clock=lambda: NOW.replace(tzinfo=None))

    with pytest.raises(ValueError, match="aware"):
        controller.update(presentation(), snapshot(MapDataStatus.READY))
