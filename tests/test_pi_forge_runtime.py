"""Tests for Pi-side Forge shared-spot runtime composition."""

from pathlib import Path

from rolling_thunder.config import ForgeConfig
from rolling_thunder.pi_forge_runtime import build_pi_forge_spot_polling
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


def test_disabled_forge_does_not_create_runtime_or_database(tmp_path: Path) -> None:
    database_path = tmp_path / "rolling-thunder.db"

    polling = build_pi_forge_spot_polling(
        ForgeConfig(),
        database_path=database_path,
        scheduler=ManualScheduler(),
    )

    assert polling is None
    assert database_path.exists() is False


def test_enabled_forge_builds_durable_polling_stack(tmp_path: Path) -> None:
    database_path = tmp_path / "rolling-thunder.db"
    scheduler = ManualScheduler()
    config = ForgeConfig.model_validate(
        {
            "enabled": True,
            "api_url": "https://forge.example.invalid/root",
            "refresh_interval_s": 45.0,
            "refresh_on_start": False,
        }
    )

    polling = build_pi_forge_spot_polling(
        config,
        database_path=database_path,
        scheduler=scheduler,
    )

    assert polling is not None
    assert database_path.is_file()
    assert polling.latest_state.kind is PiForgeSpotStateKind.EMPTY
    assert polling.latest_state.snapshot is None

    startup_state = polling.start()

    assert startup_state.kind is PiForgeSpotStateKind.EMPTY
    assert scheduler.interval_s == 45.0
    assert polling.is_running is True
    assert polling.is_refreshing is False

    stopped_state = polling.stop()

    assert stopped_state.kind is PiForgeSpotStateKind.EMPTY
    assert scheduler.poll is not None
    assert scheduler.poll.cancelled is True
    assert polling.is_running is False
