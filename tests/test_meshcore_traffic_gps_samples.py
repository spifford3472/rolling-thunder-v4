"""Tests for rate-limited reuse of the current GPS publication."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from rolling_thunder.domain import GPSFixState, GPSPosition
from rolling_thunder.gps import GPSConnectionState, GPSState
from rolling_thunder.meshcore_traffic_gps_samples import ExistingGpsSampler

NOW = datetime(2026, 11, 11, 16, tzinfo=UTC)


def _state(timestamp: datetime) -> GPSState:
    position = GPSPosition(
        fix_state=GPSFixState.THREE_DIMENSIONAL,
        latitude=39.54,
        longitude=-84.10,
        accuracy_m=5.0,
        updated_at=timestamp,
    )
    return GPSState(
        connection_state=GPSConnectionState.CONNECTED,
        position=position,
        updated_at=timestamp,
    )


def test_rate_limit_and_sample_span_without_new_gps_reader() -> None:
    ticks = [100.0]
    calls: list[Path] = []
    date = [NOW - timedelta(seconds=3)]

    def read(path: Path) -> GPSState:
        calls.append(path)
        return _state(date[0])

    sampler = ExistingGpsSampler(
        Path("/tmp/not-opened-by-fake"),
        reader=read,
        clock=lambda: ticks[0],
    )
    assert sampler.sample()
    ticks[0] = 100.3
    assert not sampler.sample()
    assert len(calls) == 1
    ticks[0] = 103
    date[0] = NOW
    assert sampler.sample()
    assert len(calls) == 2
    assert sampler.history.has_recent_span(NOW)


def test_missing_snapshot_does_not_create_a_gps_pipeline() -> None:
    ticks = [100.0]
    sampler = ExistingGpsSampler(
        Path("/tmp/missing"),
        reader=lambda _path: None,
        clock=lambda: ticks[0],
    )
    assert not sampler.sample()
    assert not sampler.sample()
    assert not sampler.history.has_recent_span(NOW)
    ticks[0] += 1
    assert not sampler.sample()


def test_unchanged_position_timestamp_does_not_invent_new_sample() -> None:
    ticks = [100.0]
    sampler = ExistingGpsSampler(
        Path("/tmp/none"),
        reader=lambda _path: _state(NOW),
        clock=lambda: ticks[0],
    )
    assert sampler.sample()
    ticks[0] += 2
    assert not sampler.sample()
    assert not sampler.history.has_recent_span(NOW)
