"""Persistent DXSpider stream adapter for the independent Forge service."""

from __future__ import annotations

import socket
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from threading import Event, RLock, Thread
from time import monotonic
from typing import Protocol

from rolling_thunder.forge_config import ForgeDxSpiderProviderConfig
from rolling_thunder.forge_dx_connection import ForgeDxConnectionStatus
from rolling_thunder.forge_dx_spot_parser import (
    DxSpotLineError,
    is_dx_spot_line,
    parse_dx_spot_line,
)
from rolling_thunder.forge_spot_provider import (
    ForgeProviderSlice,
    ForgeSpotProviderConnectionError,
    ForgeSpotProviderError,
)
from rolling_thunder.spot_domain import SpotProvider, SpotRecord

_IAC = 255
_SE = 240
_SB = 250
_WILL = 251
_WONT = 252
_DO = 253
_DONT = 254
_NEGOTIATION_COMMANDS = frozenset({_WILL, _WONT, _DO, _DONT})
_READ_CHUNK_BYTES = 4_096

Clock = Callable[[], datetime]
MonotonicClock = Callable[[], float]


class DxSpiderConnectionState(StrEnum):
    """Observable lifecycle states for the persistent DXSpider connection."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    LIVE = "live"
    BACKING_OFF = "backing_off"
    STOPPED = "stopped"


class DxSpiderSession(Protocol):
    """One long-lived connection to a DXSpider-compatible node."""

    def send_line(self, line: str) -> None:
        """Send one ASCII command line terminated for a telnet-style service."""
        ...

    def read(self, max_bytes: int) -> bytes | None:
        """Read bytes, returning None for a bounded read timeout."""
        ...

    def close(self) -> None:
        """Close the connection and release its resources."""
        ...


class DxSpiderSessionFactory(Protocol):
    """Open one configured DXSpider session."""

    def open(
        self,
        *,
        host: str,
        port: int,
        connect_timeout_s: float,
        read_timeout_s: float,
    ) -> DxSpiderSession:
        """Open one persistent session."""
        ...


class SocketDxSpiderSession:
    """Standard-library socket implementation of one persistent DXSpider session."""

    def __init__(self, connection: socket.socket) -> None:
        self._connection = connection

    def send_line(self, line: str) -> None:
        self._connection.sendall(line.encode("ascii") + b"\r\n")

    def read(self, max_bytes: int) -> bytes | None:
        try:
            chunk = self._connection.recv(max_bytes)
        except TimeoutError:
            return None
        if not chunk:
            raise ConnectionError("DXSpider server closed the connection.")
        return chunk

    def close(self) -> None:
        self._connection.close()


class SocketDxSpiderSessionFactory:
    """Production factory using one persistent TCP connection."""

    def open(
        self,
        *,
        host: str,
        port: int,
        connect_timeout_s: float,
        read_timeout_s: float,
    ) -> DxSpiderSession:
        try:
            connection = socket.create_connection(
                (host, port),
                timeout=connect_timeout_s,
            )
            connection.settimeout(read_timeout_s)
            connection.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        except (TimeoutError, OSError) as error:
            raise ForgeSpotProviderConnectionError(
                "DXSpider connection could not be established."
            ) from error
        return SocketDxSpiderSession(connection)


class ForgeDxSpiderSpotProvider:
    """Maintain one persistent DXSpider connection and expose a cached DX slice."""

    def __init__(
        self,
        config: ForgeDxSpiderProviderConfig,
        *,
        session_factory: DxSpiderSessionFactory | None = None,
        clock: Clock | None = None,
        monotonic_clock: MonotonicClock = monotonic,
    ) -> None:
        self._config = config
        self._session_factory = session_factory or SocketDxSpiderSessionFactory()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._monotonic = monotonic_clock

        self._lock = RLock()
        self._stop = Event()
        self._thread: Thread | None = None
        self._session: DxSpiderSession | None = None
        self._cache: dict[str, SpotRecord] = {}
        self._state = DxSpiderConnectionState.DISCONNECTED
        self._connected_since: datetime | None = None
        self._last_message_at: datetime | None = None
        self._last_spot_at: datetime | None = None
        self._reconnect_count = 0
        self._last_error: str | None = None
        self._live_started_monotonic: float | None = None

    @property
    def provider(self) -> SpotProvider:
        return SpotProvider.DX

    @property
    def connection_status(self) -> ForgeDxConnectionStatus:
        """Return provider-neutral connection status without network activity."""
        now = self._normalized_clock_value()
        with self._lock:
            self._prune_cache_locked(now)
            return ForgeDxConnectionStatus(
                source="dxspider",
                state=self._state.value,
                host=self._config.host,
                port=self._config.port,
                channel=None,
                nickname=str(self._config.login_callsign),
                connected_since=self._connected_since,
                last_message_at=self._last_message_at,
                last_spot_at=self._last_spot_at,
                reconnect_count=self._reconnect_count,
                cache_size=len(self._cache),
                last_error=self._last_error,
            )

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._thread is not None

    @property
    def connection_state(self) -> DxSpiderConnectionState:
        with self._lock:
            return self._state

    def start(self) -> None:
        """Start exactly one background DXSpider connection loop."""
        with self._lock:
            if self._thread is not None:
                raise RuntimeError("DXSpider source is already running.")
            self._stop.clear()
            self._state = DxSpiderConnectionState.DISCONNECTED
            self._thread = Thread(
                target=self._run,
                name="rolling-thunder-dxspider",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        """Stop the background connection and close the current socket."""
        with self._lock:
            thread = self._thread
            session = self._session
            self._stop.set()

        if session is not None:
            try:
                session.send_line("bye")
            except (OSError, ConnectionError):
                pass
            try:
                session.close()
            except OSError:
                pass

        if thread is not None:
            thread.join(timeout=max(5.0, self._config.read_timeout_s + 1.0))

        with self._lock:
            self._thread = None
            self._session = None
            self._state = DxSpiderConnectionState.STOPPED
            self._connected_since = None

    def fetch_slice(self) -> ForgeProviderSlice:
        """Return the current cache without opening or touching the network."""
        fetched_at = self._normalized_clock_value()
        with self._lock:
            if self._state is not DxSpiderConnectionState.LIVE:
                detail = f": {self._last_error}" if self._last_error else ""
                raise ForgeSpotProviderConnectionError(
                    f"DXSpider source is not live ({self._state.value}){detail}"
                )
            self._prune_cache_locked(fetched_at)
            spots = tuple(self._cache.values())

        return ForgeProviderSlice.from_spots(
            provider=self.provider,
            fetched_at=fetched_at,
            spots=spots,
        )

    def _run(self) -> None:
        delay = self._config.reconnect_initial_s
        first_connection = True

        while not self._stop.is_set():
            with self._lock:
                self._live_started_monotonic = None

            try:
                self._set_state(DxSpiderConnectionState.CONNECTING)
                session = self._open_session()
                with self._lock:
                    self._session = session
                    self._connected_since = self._normalized_clock_value()
                    self._last_error = None
                    if not first_connection:
                        self._reconnect_count += 1

                self._send_initial_commands(session)
                self._set_state(DxSpiderConnectionState.LIVE)
                with self._lock:
                    self._live_started_monotonic = self._monotonic()
                self._consume_session(session)
                first_connection = False
            except (ForgeSpotProviderError, ConnectionError, OSError, TimeoutError) as error:
                first_connection = False
                self._record_disconnect(error)
            finally:
                self._close_current_session()

            if self._stop.is_set():
                break

            with self._lock:
                live_started = self._live_started_monotonic
            if (
                live_started is not None
                and self._monotonic() - live_started >= self._config.stable_connection_s
            ):
                delay = self._config.reconnect_initial_s

            self._set_state(DxSpiderConnectionState.BACKING_OFF)
            if self._stop.wait(delay):
                break
            delay = min(delay * 2.0, self._config.reconnect_max_s)

        with self._lock:
            if self._state is not DxSpiderConnectionState.STOPPED:
                self._state = DxSpiderConnectionState.STOPPED

    def _open_session(self) -> DxSpiderSession:
        try:
            return self._session_factory.open(
                host=self._config.host,
                port=self._config.port,
                connect_timeout_s=self._config.connect_timeout_s,
                read_timeout_s=self._config.read_timeout_s,
            )
        except ForgeSpotProviderError:
            raise
        except (TimeoutError, OSError) as error:
            raise ForgeSpotProviderConnectionError(
                "DXSpider connection could not be established."
            ) from error

    def _send_initial_commands(self, session: DxSpiderSession) -> None:
        """Login and seed once per real connection; never send bye here."""
        for line in (
            str(self._config.login_callsign),
            "set/page 0",
            "show/fdx",
        ):
            session.send_line(line)

    def _consume_session(self, session: DxSpiderSession) -> None:
        last_rx_monotonic = self._monotonic()
        buffer = bytearray()

        while not self._stop.is_set():
            chunk = session.read(_READ_CHUNK_BYTES)
            now_monotonic = self._monotonic()

            if chunk is None:
                if (
                    now_monotonic - last_rx_monotonic
                    >= self._config.inactivity_timeout_s
                ):
                    raise ConnectionError(
                        "DXSpider connection exceeded the inactivity timeout."
                    )
                continue

            last_rx_monotonic = now_monotonic
            with self._lock:
                self._last_message_at = self._normalized_clock_value()
            buffer.extend(strip_telnet_negotiation(chunk))
            if len(buffer) > self._config.max_response_bytes:
                raise ConnectionError(
                    "DXSpider buffered data exceeded the configured byte limit."
                )

            while b"\n" in buffer:
                raw, _, remainder = buffer.partition(b"\n")
                buffer = bytearray(remainder)
                line = raw.rstrip(b"\r").decode("utf-8", errors="replace")
                self._accept_line(line)

    def _accept_line(self, line: str) -> None:
        if not is_dx_spot_line(line):
            return

        received_at = self._normalized_clock_value()
        try:
            spot = parse_dx_spot_line(line, fetched_at=received_at)
        except DxSpotLineError:
            return

        with self._lock:
            if received_at - spot.spotted_at <= timedelta(
                seconds=self._config.max_spot_age_s
            ):
                self._cache[spot.stable_key] = spot
                self._last_spot_at = received_at
                self._prune_cache_locked(received_at)

    def _prune_cache_locked(self, now: datetime) -> None:
        cutoff = now - timedelta(seconds=self._config.max_spot_age_s)
        self._cache = {
            key: spot
            for key, spot in self._cache.items()
            if spot.spotted_at >= cutoff
        }
        if len(self._cache) <= self._config.max_spots:
            return

        newest = sorted(
            self._cache.values(),
            key=lambda spot: (spot.spotted_at, spot.stable_key),
            reverse=True,
        )[: self._config.max_spots]
        self._cache = {spot.stable_key: spot for spot in newest}

    def _record_disconnect(self, error: BaseException) -> None:
        text = (str(error).strip() or error.__class__.__name__)[:500]
        with self._lock:
            self._last_error = text
            self._state = DxSpiderConnectionState.DISCONNECTED
            self._connected_since = None

    def _close_current_session(self) -> None:
        with self._lock:
            session = self._session
            self._session = None
        if session is not None:
            try:
                session.close()
            except OSError:
                pass

    def _set_state(self, state: DxSpiderConnectionState) -> None:
        with self._lock:
            self._state = state

    def _normalized_clock_value(self) -> datetime:
        fetched_at = self._clock()
        if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
            raise ValueError("DXSpider provider clock must return an aware datetime.")
        return fetched_at.astimezone(UTC)


def strip_telnet_negotiation(data: bytes) -> bytes:
    """Remove common telnet negotiation sequences from one received chunk."""
    output = bytearray()
    index = 0

    while index < len(data):
        value = data[index]
        if value != _IAC:
            output.append(value)
            index += 1
            continue

        if index + 1 >= len(data):
            break
        command = data[index + 1]

        if command == _IAC:
            output.append(_IAC)
            index += 2
            continue

        if command in _NEGOTIATION_COMMANDS:
            index = min(index + 3, len(data))
            continue

        if command == _SB:
            index += 2
            while index + 1 < len(data):
                if data[index] == _IAC and data[index + 1] == _SE:
                    index += 2
                    break
                index += 1
            else:
                index = len(data)
            continue

        index += 2

    return bytes(output)
