"""Tests for live-map application runtime composition and lifecycle."""

from concurrent.futures import Executor, Future
from pathlib import Path
from typing import Any

from rolling_thunder.application_runtime import ApplicationRuntime
from rolling_thunder.config import ApplicationConfig
from rolling_thunder.live_map_service import MapDataStatus
from rolling_thunder.map_sources import MapPackageStyle
from rolling_thunder.radio_polling import PollCallback


class ManualScheduledPoll:
    def __init__(self, callback: PollCallback) -> None:
        self.callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class ManualScheduler:
    def __init__(self) -> None:
        self.polls: list[ManualScheduledPoll] = []

    def schedule_repeating(
        self,
        interval_s: float,
        callback: PollCallback,
    ) -> ManualScheduledPoll:
        assert interval_s == 1.0
        poll = ManualScheduledPoll(callback)
        self.polls.append(poll)
        return poll


class SolarManualScheduler:
    def __init__(self) -> None:
        self.intervals: list[float] = []
        self.polls: list[ManualScheduledPoll] = []

    def schedule_repeating(
        self,
        interval_s: float,
        callback: PollCallback,
    ) -> ManualScheduledPoll:
        self.intervals.append(interval_s)
        poll = ManualScheduledPoll(callback)
        self.polls.append(poll)
        return poll


class NoopExecutor(Executor):
    def submit(
        self,
        fn: Any,
        /,
        *args: Any,
        **kwargs: Any,
    ) -> Future[Any]:
        return Future()


def config(
    tmp_path: Path,
    *,
    map_enabled: bool,
    callsign_info_enabled: bool = False,
    map_style: str = "day",
) -> ApplicationConfig:
    return ApplicationConfig.model_validate(
        {
            "operator": {
                "callsign": "KI5VNB",
                "home_grid": "EM79xm",
            },
            "hardware": {"mock": True},
            "map": {
                "enabled": map_enabled,
                "cache_directory": tmp_path / "map-cache",
                "installed_packages": ([tmp_path / "missing-ohio.mbtiles"] if map_enabled else []),
                "style": map_style,
                "callsign_tile_url_template": (
                    "http://forge:8766/api/v1/map/tiles/{style}/{z}/{x}/{y}.png"
                ),
            },
            "forge": {
                "enabled": callsign_info_enabled,
                "api_url": ("http://forge:8765" if callsign_info_enabled else None),
                "callsign_info": {
                    "enabled": callsign_info_enabled,
                    "api_url": ("http://forge:8788" if callsign_info_enabled else None),
                },
            },
            "storage": {
                "database_path": tmp_path / "rolling-thunder.db",
            },
        }
    )


def test_runtime_composes_disabled_map_as_none(tmp_path: Path) -> None:
    runtime = ApplicationRuntime.from_config(
        config(tmp_path, map_enabled=False),
        scheduler=ManualScheduler(),
        gps_scheduler=ManualScheduler(),
    )

    assert runtime.live_map is None
    assert runtime.latest_live_map_state is None


def test_runtime_starts_and_stops_enabled_map(tmp_path: Path) -> None:
    solar_scheduler = SolarManualScheduler()
    runtime = ApplicationRuntime.from_config(
        config(tmp_path, map_enabled=True),
        scheduler=ManualScheduler(),
        gps_scheduler=ManualScheduler(),
        map_solar_scheduler=solar_scheduler,
        map_executor=NoopExecutor(),
    )

    assert runtime.live_map is not None
    assert runtime.latest_live_map_state is not None
    assert runtime.latest_live_map_state.status is MapDataStatus.IDLE
    assert runtime.live_map.installed_packages == ()
    assert len(runtime.live_map.source_diagnostics) == 1
    assert "missing-ohio.mbtiles" in runtime.live_map.source_diagnostics[0]

    runtime.start()

    assert runtime.live_map.is_running is True
    assert runtime.map_solar is not None
    assert runtime.map_solar.is_running is True
    assert solar_scheduler.polls

    runtime.stop()

    assert runtime.live_map.is_running is False
    assert runtime.map_solar.is_running is False
    assert solar_scheduler.polls[-1].cancelled is True


def test_callsign_map_starts_with_configured_main_map_style(tmp_path: Path) -> None:
    runtime = ApplicationRuntime.from_config(
        config(
            tmp_path,
            map_enabled=True,
            callsign_info_enabled=True,
            map_style="night",
        ),
        scheduler=ManualScheduler(),
        gps_scheduler=ManualScheduler(),
        map_solar_scheduler=SolarManualScheduler(),
        map_executor=NoopExecutor(),
        callsign_map_executor=NoopExecutor(),
    )

    assert runtime.live_map is not None
    assert runtime.callsign_map is not None
    assert runtime.live_map.style is MapPackageStyle.NIGHT
    assert runtime.callsign_map.style is runtime.live_map.style
