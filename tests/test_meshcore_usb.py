"""Tests for the non-blocking MeshCore USB receive boundary."""

from collections.abc import Callable
from pathlib import Path
from threading import Event, get_ident
from time import monotonic, sleep
from types import SimpleNamespace

import pytest

from rolling_thunder.meshcore_messages import MeshCoreMessageOverlayService
from rolling_thunder.meshcore_usb import (
    ExclusiveMeshCoreMessageSource,
    MeshCorePythonUsbSource,
    MeshCoreReceiveService,
    ensure_exclusive_meshcore_device,
)


class BlockingFakeSource:
    def __init__(self) -> None:
        self.started = Event()
        self.worker_ident: int | None = None

    def run(
        self,
        on_message: Callable[[str, str], None],
        stop_event: Event,
        on_connected: Callable[[], None],
    ) -> None:
        self.worker_ident = get_ident()
        on_connected()
        self.started.set()
        on_message("#skywarn", "Live warning")
        stop_event.wait()


def test_exclusive_source_allows_distinct_resolved_devices(tmp_path: Path) -> None:
    meshcore_target = tmp_path / "meshcore-target"
    controls_target = tmp_path / "controls-target"
    meshcore_target.touch()
    controls_target.touch()
    meshcore_path = tmp_path / "meshcore"
    controls_path = tmp_path / "controls"
    meshcore_path.symlink_to(meshcore_target)
    controls_path.symlink_to(controls_target)
    source = BlockingFakeSource()
    protected = ExclusiveMeshCoreMessageSource(
        source,
        meshcore_path,
        {"physical controls": controls_path},
    )
    stop_event = Event()
    stop_event.set()

    protected.run(lambda _channel, _message: None, stop_event, lambda: None)

    assert source.started.is_set()


def test_meshcore_guard_rejects_paths_resolving_to_same_device(tmp_path: Path) -> None:
    shared_target = tmp_path / "shared-target"
    shared_target.touch()
    meshcore_path = tmp_path / "meshcore"
    controls_path = tmp_path / "controls"
    meshcore_path.symlink_to(shared_target)
    controls_path.symlink_to(shared_target)

    with pytest.raises(RuntimeError, match="active physical controls device"):
        ensure_exclusive_meshcore_device(
            meshcore_path,
            {"physical controls": controls_path},
        )


def test_meshcore_guard_rejects_identical_missing_configured_path(
    tmp_path: Path,
) -> None:
    shared_path = tmp_path / "missing-device"

    with pytest.raises(RuntimeError, match="conflicts with GPS"):
        ensure_exclusive_meshcore_device(shared_path, {"GPS": shared_path})


def test_meshcore_guard_rejects_unavailable_device(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing-meshcore"

    with pytest.raises(RuntimeError, match="is unavailable"):
        ensure_exclusive_meshcore_device(missing_path, {})


def test_usb_receive_runs_off_caller_thread_and_publishes_prepared_state() -> None:
    source = BlockingFakeSource()
    overlay = MeshCoreMessageOverlayService(("#skywarn",))
    service = MeshCoreReceiveService(source, overlay, reconnect_delay_s=0.01)
    caller_ident = get_ident()

    service.start()
    assert source.started.wait(timeout=1.0)

    state = overlay.latest_state
    assert source.worker_ident is not None
    assert source.worker_ident != caller_ident
    assert state is not None
    assert state.channel == "#skywarn"
    assert state.message == "Live warning"

    service.stop()
    assert service.latest_state.running is False


def test_runtime_factory_receives_configured_usb_settings(tmp_path: Path) -> None:
    from rolling_thunder.application_runtime import ApplicationRuntime
    from rolling_thunder.config import ApplicationConfig

    source = BlockingFakeSource()
    received: list[tuple[Path, int, float]] = []

    def source_factory(
        device: Path,
        *,
        baud_rate: int,
        command_timeout_s: float,
    ) -> BlockingFakeSource:
        received.append((device, baud_rate, command_timeout_s))
        return source

    config = ApplicationConfig.model_validate(
        {
            "operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
            "hardware": {"mock": True},
            "meshcore": {
                "enabled": True,
                "device": "/dev/serial/by-id/meshcore",
                "baud_rate": 115_200,
                "channels": ["#skywarn"],
            },
            "storage": {"database_path": tmp_path / "contacts.db"},
        }
    )

    runtime = ApplicationRuntime.from_config(
        config,
        meshcore_source_factory=source_factory,
    )

    assert received == [(Path("/dev/serial/by-id/meshcore"), 115_200, 2.0)]
    assert runtime.meshcore_receive is not None


def test_runtime_conflict_stays_inside_optional_meshcore_worker(tmp_path: Path) -> None:
    from rolling_thunder.application_runtime import ApplicationRuntime
    from rolling_thunder.config import ApplicationConfig

    shared_path = tmp_path / "shared-device"
    source = BlockingFakeSource()
    config = ApplicationConfig.model_validate(
        {
            "operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
            "hardware": {"mock": True},
            "meshcore": {"enabled": True, "device": str(shared_path)},
            "physical_controls": {
                "enabled": True,
                "transport": "serial",
                "device": str(shared_path),
            },
            "storage": {"database_path": tmp_path / "contacts.db"},
        }
    )
    runtime = ApplicationRuntime.from_config(
        config,
        meshcore_source_factory=lambda *_args, **_kwargs: source,
    )
    service = runtime.meshcore_receive
    assert service is not None

    service.start()
    deadline = monotonic() + 1.0
    while service.latest_state.last_error is None and monotonic() < deadline:
        sleep(0.01)

    assert service.latest_state.running is True
    assert service.latest_state.connected is False
    assert service.latest_state.last_error is not None
    assert "physical controls" in service.latest_state.last_error
    assert source.started.is_set() is False
    service.stop()


class FakeCommands:
    def __init__(self) -> None:
        self.message_types = ["channel_message", "contact_message", "no_more"]
        self.channel_payloads = {
            0: {"channel_name": "#hamradio"},
            2: {"channel_name": "#traffic"},
        }
        self.get_msg_calls = 0

    async def get_channel(self, channel_index: int) -> SimpleNamespace:
        payload = self.channel_payloads.get(channel_index, {"channel_name": ""})
        return SimpleNamespace(type="channel_info", payload=payload)

    async def get_msg(self, timeout: float) -> SimpleNamespace:
        assert timeout == 2.0
        self.get_msg_calls += 1
        return SimpleNamespace(type=self.message_types.pop(0), payload={})


@pytest.mark.asyncio
async def test_usb_source_discovers_names_and_drains_history_to_live_baseline() -> None:
    source = MeshCorePythonUsbSource(Path("/dev/serial/by-id/meshcore"))
    commands = FakeCommands()
    client = SimpleNamespace(commands=commands)
    event_types = SimpleNamespace(
        ERROR="error",
        NO_MORE_MSGS="no_more",
    )

    channels = await source._read_channels(client, event_types, Event())
    await source._discard_startup_messages(client, event_types, Event())

    assert channels == {0: "#hamradio", 2: "#traffic"}
    assert commands.get_msg_calls == 3
