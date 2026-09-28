"""Tests for the independent Forge spot-service composition root."""

import logging
from collections.abc import Mapping
from pathlib import Path

import pytest

from rolling_thunder.forge_config import ForgeApplicationConfig
from rolling_thunder.forge_spot_api import ForgeSpotApiApplication
from rolling_thunder.forge_spot_main import (
    EXIT_CONFIGURATION_ERROR,
    ForgeRuntimeConfigurationError,
    build_forge_runtime,
    build_parser,
    main,
)
from rolling_thunder.http_home_platform import HttpResponse
from rolling_thunder.radio_polling import PollCallback


class ManualScheduledPoll:
    def __init__(self, callback: PollCallback) -> None:
        self.callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class RecordingScheduler:
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


class RecordingTransport:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, float]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_s: float,
    ) -> HttpResponse:
        del headers, body
        self.requests.append((method, url, timeout_s))
        raise AssertionError("composition must not perform provider HTTP")


class FakeServer:
    def __init__(self) -> None:
        self.serve_count = 0
        self.shutdown_count = 0
        self.close_count = 0

    @property
    def server_address(self) -> tuple[str, int]:
        return "127.0.0.1", 8765

    def serve_forever(self) -> None:
        self.serve_count += 1

    def shutdown(self) -> None:
        self.shutdown_count += 1

    def close(self) -> None:
        self.close_count += 1


def config_for(tmp_path: Path, *, enabled: bool = True) -> ForgeApplicationConfig:
    return ForgeApplicationConfig.model_validate(
        {
            "storage": {"database_path": tmp_path / "forge.db"},
            "aggregation": {
                "refresh_interval_s": 45,
                "refresh_on_start": False,
            },
            "pota": {
                "enabled": enabled,
                "base_url": "https://api.pota.app",
                "request_timeout_s": 3.5,
            },
        }
    )


def test_parser_uses_independent_program_and_default_config() -> None:
    parser = build_parser()
    args = parser.parse_args([])

    assert parser.prog == "rolling-thunder-forge-spots"
    assert args.config == Path("config/forge-spots.yaml")


def test_build_runtime_does_not_fetch_provider_or_use_real_server(tmp_path: Path) -> None:
    scheduler = RecordingScheduler()
    transport = RecordingTransport()
    fake_server = FakeServer()
    captured: list[tuple[str, int, ForgeSpotApiApplication]] = []

    def server_factory(
        host: str,
        port: int,
        application: ForgeSpotApiApplication,
    ) -> FakeServer:
        captured.append((host, port, application))
        return fake_server

    runtime = build_forge_runtime(
        config_for(tmp_path),
        scheduler=scheduler,
        server_factory=server_factory,
        transport=transport,
        logger=logging.getLogger("test.forge"),
    )

    assert transport.requests == []
    assert captured[0][:2] == ("127.0.0.1", 8765)
    assert scheduler.intervals == []

    runtime.run()

    assert transport.requests == []
    assert scheduler.intervals == [45]
    assert scheduler.polls[0].cancelled is True
    assert fake_server.serve_count == 1
    assert fake_server.shutdown_count == 1
    assert fake_server.close_count == 1


def test_disabled_only_provider_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ForgeRuntimeConfigurationError, match="No Forge spot provider"):
        build_forge_runtime(
            config_for(tmp_path, enabled=False),
            server_factory=lambda host, port, application: FakeServer(),
        )


def test_missing_configuration_returns_configuration_exit_code(tmp_path: Path) -> None:
    result = main(("--config", str(tmp_path / "missing.yaml")))

    assert result == EXIT_CONFIGURATION_ERROR
