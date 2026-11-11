"""GPS snapshot bridge tests: no additional GPS device or network required."""
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event

from rolling_thunder.domain import GPSFixState, GPSPosition
from rolling_thunder.gps import GPSConnectionState, GPSState
from rolling_thunder.meshcore_gps_bridge import (
    MeshcoreGpsPublisher,
    read_meshcore_gps_snapshot,
)


def _gps() -> GPSState:
    now = datetime.now(UTC)
    return GPSState(
        connection_state=GPSConnectionState.CONNECTED,
        position=GPSPosition(
            fix_state=GPSFixState.THREE_DIMENSIONAL,
            latitude=39.5,
            longitude=-84.1,
            accuracy_m=6.0,
            updated_at=now,
        ),
        updated_at=now,
    )


def test_no_extra_receiver_and_atomic_publication(tmp_path: Path) -> None:
    path = tmp_path / "gps.json"
    publisher = MeshcoreGpsPublisher(path)
    publisher.offer(_gps())
    assert not path.exists(), "No I/O may run before the publisher starts"
    publisher.start()
    publisher.offer(_gps())
    try:
        for _ in range(100):
            state = read_meshcore_gps_snapshot(path)
            if state is not None:
                break
            Event().wait(0.01)
        else:
            raise AssertionError("No GPS publication observed")
        assert state is not None
        assert state.position is not None
        assert state.position.latitude == 39.5
        assert state.position.longitude == -84.1
        assert not path.with_name("gps.json.tmp").exists()
    finally:
        publisher.stop()


def test_missing_and_stale_snapshots_fail_closed(tmp_path: Path) -> None:
    import json

    path = tmp_path / "gps.json"
    assert read_meshcore_gps_snapshot(path) is None
    now = datetime.now(UTC)
    data = {
        "connection": "connected",
        "published_at": (now - timedelta(seconds=40)).isoformat(),
        "fix": "3d",
        "latitude": 39.5,
        "longitude": -84.1,
        "accuracy_m": 6,
        "updated_at": (now - timedelta(seconds=40)).isoformat(),
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    assert read_meshcore_gps_snapshot(path) is None
    data["published_at"] = now.isoformat()
    data["connection"] = "disconnected"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert read_meshcore_gps_snapshot(path) is None
