"""Focused ApplicationRuntime tests for optional Pi Forge services."""

from pathlib import Path

from rolling_thunder.application_runtime import ApplicationRuntime
from rolling_thunder.config import ApplicationConfig
from rolling_thunder.mock_gps import MockGPSReceiver
from rolling_thunder.pi_forge_spot_service import PiForgeSpotStateKind
from rolling_thunder.radio_polling import PollCallback


class ManualScheduledPoll:
    def __init__(self, callback: PollCallback) -> None:
        self.callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class ManualScheduler:
    def __init__(self) -> None:
        self.interval_s: float | None = None
        self.poll: ManualScheduledPoll | None = None

    def schedule_repeating(
        self,
        interval_s: float,
        callback: PollCallback,
    ) -> ManualScheduledPoll:
        self.interval_s = interval_s
        self.poll = ManualScheduledPoll(callback)
        return self.poll


def config(
    tmp_path: Path,
    *,
    forge_enabled: bool,
    real_gps: bool = False,
) -> ApplicationConfig:
    hardware: dict[str, object] = {"mock": True}
    if real_gps:
        hardware.update(
            {
                "gps_mode": "real",
                "gps_device": "/dev/fake-gps",
            }
        )

    payload: dict[str, object] = {
        "operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
        "hardware": hardware,
        "storage": {"database_path": str(tmp_path / "rolling-thunder.db")},
    }
    if forge_enabled:
        payload["forge"] = {
            "enabled": True,
            "api_url": "http://forge.example.invalid",
            "refresh_interval_s": 45.0,
            "refresh_on_start": False,
        }
    return ApplicationConfig.model_validate(payload)


def test_runtime_leaves_pi_forge_stack_absent_when_disabled(tmp_path: Path) -> None:
    runtime = ApplicationRuntime.from_config(
        config(tmp_path, forge_enabled=False),
        scheduler=ManualScheduler(),
        gps_scheduler=ManualScheduler(),
    )

    assert runtime.pi_forge_spot_polling is None
    assert runtime.pi_forge_location_publishing is None
    assert runtime.latest_forge_spot_state is None
    assert runtime.latest_forge_location_publisher_state is None


def test_runtime_composes_and_manages_enabled_pi_forge_polling(tmp_path: Path) -> None:
    radio_scheduler = ManualScheduler()
    gps_scheduler = ManualScheduler()
    forge_scheduler = ManualScheduler()
    runtime = ApplicationRuntime.from_config(
        config(tmp_path, forge_enabled=True),
        scheduler=radio_scheduler,
        gps_scheduler=gps_scheduler,
        forge_scheduler=forge_scheduler,
    )

    forge_polling = runtime.pi_forge_spot_polling
    assert forge_polling is not None
    initial = runtime.latest_forge_spot_state
    assert initial is not None
    assert initial.kind is PiForgeSpotStateKind.EMPTY
    assert initial.snapshot is None
    assert forge_polling.is_running is False

    # Mock/development GPS must never publish fake coordinates to Forge.
    assert runtime.pi_forge_location_publishing is None
    assert runtime.latest_forge_location_publisher_state is None

    runtime.start()

    assert forge_polling.is_running is True
    assert forge_polling.is_refreshing is False
    assert forge_scheduler.interval_s == 45.0
    assert forge_scheduler.poll is not None
    assert runtime.latest_forge_spot_state is forge_polling.latest_state

    runtime.stop()

    assert forge_polling.is_running is False
    assert forge_scheduler.poll.cancelled is True


def test_real_gps_mode_composes_and_manages_location_publisher(tmp_path: Path) -> None:
    radio_scheduler = ManualScheduler()
    gps_scheduler = ManualScheduler()
    forge_scheduler = ManualScheduler()
    location_scheduler = ManualScheduler()
    runtime = ApplicationRuntime.from_config(
        config(tmp_path, forge_enabled=True, real_gps=True),
        scheduler=radio_scheduler,
        gps_scheduler=gps_scheduler,
        forge_scheduler=forge_scheduler,
        forge_location_scheduler=location_scheduler,
        gps_factory=lambda *_args, **_kwargs: MockGPSReceiver(),
    )

    publishing = runtime.pi_forge_location_publishing
    assert publishing is not None
    assert publishing.is_running is False
    assert runtime.latest_forge_location_publisher_state is publishing.latest_state

    runtime.start()

    assert publishing.is_running is True
    assert location_scheduler.interval_s == 30.0
    assert location_scheduler.poll is not None

    runtime.stop()

    assert publishing.is_running is False
    assert location_scheduler.poll.cancelled is True
