"""Background-only MeshCore USB companion receive integration."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from threading import Event as ThreadEvent
from threading import Lock, Thread
from typing import Any, Protocol

from rolling_thunder.meshcore_messages import MeshCoreMessageOverlayService

MeshCoreMessageCallback = Callable[[str, str], None]
MeshCoreConnectedCallback = Callable[[], None]
_MAX_STARTUP_MESSAGES = 2_048


class MeshCoreMessageSource(Protocol):
    """Blocking adapter boundary owned by a background receive service."""

    def run(
        self,
        on_message: MeshCoreMessageCallback,
        stop_event: ThreadEvent,
        on_connected: MeshCoreConnectedCallback,
    ) -> None:
        """Run until stopped or disconnected, invoking only for live messages."""


class ExclusiveMeshCoreMessageSource:
    """Fail closed before a MeshCore source can claim another serial device."""

    def __init__(
        self,
        source: MeshCoreMessageSource,
        device: Path,
        reserved_devices: Mapping[str, Path],
    ) -> None:
        self._source = source
        self._device = device
        self._reserved_devices = dict(reserved_devices)

    def run(
        self,
        on_message: MeshCoreMessageCallback,
        stop_event: ThreadEvent,
        on_connected: MeshCoreConnectedCallback,
    ) -> None:
        """Validate ownership on every reconnect before performing USB I/O."""
        ensure_exclusive_meshcore_device(self._device, self._reserved_devices)
        self._source.run(on_message, stop_event, on_connected)


def ensure_exclusive_meshcore_device(
    device: Path,
    reserved_devices: Mapping[str, Path],
) -> None:
    """Require an available MeshCore target distinct from protected adapters."""
    for owner, reserved_device in reserved_devices.items():
        if device == reserved_device:
            raise RuntimeError(
                f"MeshCore USB device conflicts with {owner}; MeshCore remains offline."
            )

    try:
        resolved_device = device.resolve(strict=True)
    except OSError as error:
        raise RuntimeError(
            f"MeshCore USB device is unavailable at {device}; MeshCore remains offline."
        ) from error

    for owner, reserved_device in reserved_devices.items():
        try:
            resolved_reserved = reserved_device.resolve(strict=True)
        except OSError:
            continue
        if resolved_device == resolved_reserved:
            raise RuntimeError(
                f"MeshCore USB device resolves to the active {owner} device; "
                "MeshCore remains offline."
            )


@dataclass(frozen=True)
class MeshCoreReceiveState:
    """Immutable observable state for the optional USB receive worker."""

    running: bool
    connected: bool
    last_error: str | None = None


class MeshCorePythonUsbSource:
    """Official meshcore_py serial adapter; all work occurs in its owner thread."""

    def __init__(
        self,
        device: Path,
        *,
        baud_rate: int = 115_200,
        command_timeout_s: float = 2.0,
    ) -> None:
        self._device = device
        self._baud_rate = baud_rate
        self._command_timeout_s = command_timeout_s

    def run(
        self,
        on_message: MeshCoreMessageCallback,
        stop_event: ThreadEvent,
        on_connected: MeshCoreConnectedCallback,
    ) -> None:
        """Own one async serial session without touching Tkinter."""
        asyncio.run(self._run(on_message, stop_event, on_connected))

    async def _run(
        self,
        on_message: MeshCoreMessageCallback,
        stop_event: ThreadEvent,
        on_connected: MeshCoreConnectedCallback,
    ) -> None:
        from meshcore import EventType, MeshCore  # type: ignore[import-untyped]

        client = await MeshCore.create_serial(
            str(self._device),
            self._baud_rate,
            default_timeout=self._command_timeout_s,
        )
        try:
            channels = await self._read_channels(client, EventType, stop_event)
            if stop_event.is_set():
                return
            await self._discard_startup_messages(client, EventType, stop_event)
            on_connected()

            async def receive_channel(event: Any) -> None:
                payload = event.payload
                channel_index = payload.get("channel_idx")
                text = payload.get("text")
                if isinstance(channel_index, int) and isinstance(text, str):
                    channel = channels.get(channel_index)
                    if channel is not None:
                        on_message(channel, text)

            client.subscribe(EventType.CHANNEL_MSG_RECV, receive_channel)
            await client.start_auto_message_fetching()
            while not stop_event.is_set() and client.is_connected:
                await asyncio.sleep(0.1)
        finally:
            await client.stop_auto_message_fetching()
            await client.disconnect()

    async def _read_channels(
        self,
        client: Any,
        event_type: Any,
        stop_event: ThreadEvent,
    ) -> dict[int, str]:
        channels: dict[int, str] = {}
        for channel_index in range(8):
            if stop_event.is_set():
                break
            result = await client.commands.get_channel(channel_index)
            if result.type == event_type.ERROR:
                continue
            payload = result.payload
            name = payload.get("name") or payload.get("channel_name")
            if isinstance(name, str) and name.strip():
                channels[channel_index] = name.strip()
        return channels

    async def _discard_startup_messages(
        self,
        client: Any,
        event_type: Any,
        stop_event: ThreadEvent,
    ) -> None:
        """Establish a live-only baseline without publishing stored messages."""
        for _ in range(_MAX_STARTUP_MESSAGES):
            if stop_event.is_set():
                return
            result = await client.commands.get_msg(timeout=self._command_timeout_s)
            if result.type == event_type.NO_MORE_MSGS:
                return
            if result.type == event_type.ERROR:
                raise RuntimeError("MeshCore startup message synchronization failed.")
        raise RuntimeError("MeshCore startup message backlog exceeded the safe limit.")


class MeshCoreReceiveService:
    """Own reconnecting USB receive work outside the Tk/UI thread."""

    def __init__(
        self,
        source: MeshCoreMessageSource,
        overlay: MeshCoreMessageOverlayService,
        *,
        reconnect_delay_s: float = 2.0,
    ) -> None:
        if reconnect_delay_s <= 0:
            raise ValueError("MeshCore reconnect delay must be positive.")
        self._source = source
        self._overlay = overlay
        self._reconnect_delay_s = reconnect_delay_s
        self._stop_event = ThreadEvent()
        self._thread: Thread | None = None
        self._lock = Lock()
        self._state = MeshCoreReceiveState(running=False, connected=False)

    @property
    def latest_state(self) -> MeshCoreReceiveState:
        """Return current worker state without serial work."""
        with self._lock:
            return self._state

    def start(self) -> None:
        """Start a daemon worker and return immediately to the caller."""
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("MeshCore receive service is already started.")
        self._stop_event.clear()
        self._set_state(running=True, connected=False, last_error=None)
        self._thread = Thread(
            target=self._run,
            name="rolling-thunder-meshcore",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Request shutdown without allowing an optional device to hang exit."""
        self._stop_event.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=3.0)
        self._thread = None
        self._set_state(running=False, connected=False, last_error=None)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._set_state(running=True, connected=False, last_error=None)
                self._source.run(
                    self._publish,
                    self._stop_event,
                    self._mark_connected,
                )
                if not self._stop_event.is_set():
                    self._set_state(
                        running=True,
                        connected=False,
                        last_error="MeshCore USB connection closed.",
                    )
            except (OSError, RuntimeError, ValueError) as error:
                self._set_state(
                    running=True,
                    connected=False,
                    last_error=str(error),
                )
            if not self._stop_event.wait(self._reconnect_delay_s):
                continue

    def _publish(self, channel: str, message: str) -> None:
        self._overlay.publish(channel, message)

    def _mark_connected(self) -> None:
        self._set_state(running=True, connected=True, last_error=None)

    def _set_state(
        self,
        *,
        running: bool,
        connected: bool,
        last_error: str | None,
    ) -> None:
        with self._lock:
            self._state = MeshCoreReceiveState(
                running=running,
                connected=connected,
                last_error=last_error,
            )
