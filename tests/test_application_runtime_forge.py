"""Focused ApplicationRuntime tests for optional Pi Forge shared spots."""

from pathlib import Path

from rolling_thunder.application_runtime import ApplicationRuntime
from rolling_thunder.config import ApplicationConfig
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


def config(tmp_path: Path, *, forge_enabled: bool) -> ApplicationConfig:
    payload: dict[str, object] = {
        "operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
        "hardware": {"mock": True},
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
    assert runtime.latest_forge_spot_state is None


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

    runtime.start()

    assert forge_polling.is_running is True
    assert forge_polling.is_refreshing is False
    assert forge_scheduler.interval_s == 45.0
    assert forge_scheduler.poll is not None
    assert runtime.latest_forge_spot_state is forge_polling.latest_state

    runtime.stop()

    assert forge_polling.is_running is False
    assert forge_scheduler.poll.cancelled is True
