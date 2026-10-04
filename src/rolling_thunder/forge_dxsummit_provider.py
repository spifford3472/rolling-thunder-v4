"""Persistent read-only DX Summit IRC source for Forge."""

from __future__ import annotations

import socket
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from threading import Event, RLock, Thread
from time import monotonic
from typing import Protocol

from rolling_thunder.forge_dxsummit_irc_parser import parse_dxsummit_irc_line
from rolling_thunder.forge_spot_provider import (
    ForgeProviderSlice,
    ForgeSpotProviderConnectionError,
)
from rolling_thunder.spot_domain import SpotProvider, SpotRecord

Clock = Callable[[], datetime]
MonotonicClock = Callable[[], float]

_DEFAULT_READ_TIMEOUT_S = 5.0
_MAX_LINE_BYTES = 8_192


class DxSummitConnectionState(StrEnum):
    """Observable lifecycle states for the long-lived IRC connection."""

    DISABLED = "disabled"
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    REGISTERING = "registering"
    JOINING = "joining"
    LIVE = "live"
    BACKING_OFF = "backing_off"
    STOPPED = "stopped"


@dataclass(frozen=True, slots=True)
class DxSummitStatus:
    """Thread-safe status snapshot for operations and future API exposure."""

    state: DxSummitConnectionState
    server: str
    channel: str
    nickname: str
    connected_since: datetime | None
    last_message_at: datetime | None
    last_spot_at: datetime | None
    reconnect_count: int
    last_error: str | None
    cache_size: int


class DxSummitIrcSession(Protocol):
    """Minimal line-oriented IRC session used by the persistent source."""

    def send_line(self, line: str) -> None:
        """Send one IRC protocol line."""
        ...

    def read_line(self) -> str | None:
        """Read one line, returning None for a bounded socket timeout."""
        ...

    def close(self) -> None:
        """Close the underlying connection."""
        ...


class DxSummitIrcSessionFactory(Protocol):
    """Open one configured long-lived IRC session."""

    def open(
        self,
        *,
        host: str,
        port: int,
        connect_timeout_s: float,
        read_timeout_s: float,
    ) -> DxSummitIrcSession:
        """Open one IRC session."""
        ...


class SocketDxSummitIrcSession:
    """Standard-library IRC socket with bounded line reads."""

    def __init__(self, connection: socket.socket) -> None:
        self._connection = connection
        self._buffer = bytearray()

    def send_line(self, line: str) -> None:
        self._connection.sendall(line.encode("utf-8") + b"\r\n")

    def read_line(self) -> str | None:
        while b"\n" not in self._buffer:
            try:
                chunk = self._connection.recv(4096)
            except TimeoutError:
                return None
            if not chunk:
                raise ConnectionError("DX Summit IRC server closed the connection.")
            self._buffer.extend(chunk)
            if len(self._buffer) > _MAX_LINE_BYTES:
                raise ConnectionError("DX Summit IRC line exceeded the safety limit.")

        raw, _, remainder = self._buffer.partition(b"\n")
        self._buffer = bytearray(remainder)
        return raw.rstrip(b"\r").decode("utf-8", errors="replace")

    def close(self) -> None:
        self._connection.close()


class SocketDxSummitIrcSessionFactory:
    """Production factory for one persistent TCP IRC session."""

    def open(
        self,
        *,
        host: str,
        port: int,
        connect_timeout_s: float,
        read_timeout_s: float,
    ) -> DxSummitIrcSession:
        connection = socket.create_connection(
            (host, port),
            timeout=connect_timeout_s,
        )
        connection.settimeout(read_timeout_s)
        connection.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        return SocketDxSummitIrcSession(connection)


class ForgeDxSummitSpotProvider:
    """Long-lived read-only IRC source exposing cached DX slices to Forge."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        channel: str,
        nickname: str,
        connect_timeout_s: float = 15.0,
        read_timeout_s: float = _DEFAULT_READ_TIMEOUT_S,
        inactivity_timeout_s: float = 600.0,
        reconnect_initial_s: float = 5.0,
        reconnect_max_s: float = 300.0,
        stable_connection_s: float = 300.0,
        max_spot_age_s: float = 3600.0,
        max_spots: int = 500,
        session_factory: DxSummitIrcSessionFactory | None = None,
        clock: Clock | None = None,
        monotonic_clock: MonotonicClock = monotonic,
    ) -> None:
        if not host.strip():
            raise ValueError("DX Summit host must not be blank.")
        if port < 1 or port > 65_535:
            raise ValueError("DX Summit port is invalid.")
        if not channel.strip():
            raise ValueError("DX Summit channel must not be blank.")
        if not nickname.strip():
            raise ValueError("DX Summit nickname must not be blank.")
        if inactivity_timeout_s <= 0:
            raise ValueError("DX Summit inactivity timeout must be positive.")
        if reconnect_initial_s <= 0 or reconnect_max_s < reconnect_initial_s:
            raise ValueError("DX Summit reconnect bounds are invalid.")
        if stable_connection_s <= 0:
            raise ValueError("DX Summit stable connection interval must be positive.")
        if max_spot_age_s <= 0:
            raise ValueError("DX Summit maximum spot age must be positive.")
        if max_spots < 1:
            raise ValueError("DX Summit maximum cache size must be positive.")

        self._host = host.strip()
        self._port = port
        self._channel = channel.strip()
        self._nickname = nickname.strip()
        self._connect_timeout_s = connect_timeout_s
        self._read_timeout_s = read_timeout_s
        self._inactivity_timeout_s = inactivity_timeout_s
        self._reconnect_initial_s = reconnect_initial_s
        self._reconnect_max_s = reconnect_max_s
        self._stable_connection_s = stable_connection_s
        self._max_spot_age = timedelta(seconds=max_spot_age_s)
        self._max_spots = max_spots
        self._session_factory = session_factory or SocketDxSummitIrcSessionFactory()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._monotonic = monotonic_clock

        self._lock = RLock()
        self._stop = Event()
        self._thread: Thread | None = None
        self._session: DxSummitIrcSession | None = None
        self._cache: dict[str, SpotRecord] = {}
        self._state = DxSummitConnectionState.DISCONNECTED
        self._connected_since: datetime | None = None
        self._last_message_at: datetime | None = None
        self._last_spot_at: datetime | None = None
        self._reconnect_count = 0
        self._last_error: str | None = None
        self._active_nickname = self._nickname
        self._live_started_monotonic: float | None = None

    @property
    def provider(self) -> SpotProvider:
        return SpotProvider.DX

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._thread is not None

    @property
    def status(self) -> DxSummitStatus:
        with self._lock:
            self._prune_cache_locked(self._aware_now())
            return DxSummitStatus(
                state=self._state,
                server=self._host,
                channel=self._channel,
                nickname=self._active_nickname,
                connected_since=self._connected_since,
                last_message_at=self._last_message_at,
                last_spot_at=self._last_spot_at,
                reconnect_count=self._reconnect_count,
                last_error=self._last_error,
                cache_size=len(self._cache),
            )

    def start(self) -> None:
        """Start exactly one persistent background IRC connection loop."""
        with self._lock:
            if self._thread is not None:
                raise RuntimeError("DX Summit IRC source is already running.")
            self._stop.clear()
            self._state = DxSummitConnectionState.DISCONNECTED
            self._thread = Thread(
                target=self._run,
                name="rolling-thunder-dxsummit-irc",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        """Stop the receive loop and close the current socket cleanly."""
        with self._lock:
            thread = self._thread
            session = self._session
            self._stop.set()

        if session is not None:
            try:
                session.send_line("QUIT :Rolling Thunder Forge shutdown")
            except OSError:
                pass
            try:
                session.close()
            except OSError:
                pass

        if thread is not None:
            thread.join(timeout=max(5.0, self._read_timeout_s + 1.0))

        with self._lock:
            self._thread = None
            self._session = None
            self._state = DxSummitConnectionState.STOPPED
            self._connected_since = None

    def fetch_slice(self) -> ForgeProviderSlice:
        """Return the current live cache without performing any network I/O."""
        fetched_at = self._aware_now()
        with self._lock:
            if self._state is not DxSummitConnectionState.LIVE:
                raise ForgeSpotProviderConnectionError(
                    f"DX Summit IRC source is not live ({self._state.value})."
                )
            self._prune_cache_locked(fetched_at)
            spots = tuple(self._cache.values())

        return ForgeProviderSlice.from_spots(
            provider=self.provider,
            fetched_at=fetched_at,
            spots=spots,
        )

    def _run(self) -> None:
        delay = self._reconnect_initial_s
        first_connection = True

        while not self._stop.is_set():
            with self._lock:
                self._live_started_monotonic = None
            try:
                self._set_state(DxSummitConnectionState.CONNECTING)
                session = self._session_factory.open(
                    host=self._host,
                    port=self._port,
                    connect_timeout_s=self._connect_timeout_s,
                    read_timeout_s=self._read_timeout_s,
                )
                with self._lock:
                    self._session = session
                    self._active_nickname = self._nickname
                    self._connected_since = self._aware_now()
                    self._last_error = None
                    if not first_connection:
                        self._reconnect_count += 1

                self._set_state(DxSummitConnectionState.REGISTERING)
                session.send_line(f"NICK {self._nickname}")
                session.send_line(
                    f"USER {self._nickname} 0 * :{self._nickname} Rolling Thunder Forge"
                )

                self._consume_session(session)
                first_connection = False
            except (ConnectionError, OSError, TimeoutError) as error:
                first_connection = False
                self._record_disconnect(error)
            finally:
                self._close_current_session()

            if self._stop.is_set():
                break

            with self._lock:
                live_started_monotonic = self._live_started_monotonic
            if (
                live_started_monotonic is not None
                and self._monotonic() - live_started_monotonic
                >= self._stable_connection_s
            ):
                delay = self._reconnect_initial_s

            self._set_state(DxSummitConnectionState.BACKING_OFF)
            if self._stop.wait(delay):
                break
            delay = min(delay * 2.0, self._reconnect_max_s)

        with self._lock:
            if self._state is not DxSummitConnectionState.STOPPED:
                self._state = DxSummitConnectionState.STOPPED

    def _consume_session(self, session: DxSummitIrcSession) -> float | None:
        last_rx_monotonic = self._monotonic()
        live_started_monotonic: float | None = None
        nick_attempt = 0

        while not self._stop.is_set():
            line = session.read_line()
            now_monotonic = self._monotonic()
            if line is None:
                if now_monotonic - last_rx_monotonic >= self._inactivity_timeout_s:
                    raise ConnectionError(
                        "DX Summit IRC connection exceeded the inactivity timeout."
                    )
                continue

            last_rx_monotonic = now_monotonic
            received_at = self._aware_now()
            with self._lock:
                self._last_message_at = received_at

            if line.startswith("PING "):
                session.send_line("PONG " + line[5:])
                continue

            parts = line.split()
            numeric = parts[1] if len(parts) > 1 and parts[1].isdigit() else None

            if numeric == "433":
                nick_attempt += 1
                fallback = self._fallback_nickname(nick_attempt)
                with self._lock:
                    self._active_nickname = fallback
                session.send_line(f"NICK {fallback}")
                continue

            if numeric == "001":
                self._set_state(DxSummitConnectionState.JOINING)
                session.send_line(f"JOIN {self._channel}")
                continue

            if numeric == "366":
                self._set_state(DxSummitConnectionState.LIVE)
                live_started_monotonic = self._monotonic()
                with self._lock:
                    self._live_started_monotonic = live_started_monotonic
                continue

            spot = parse_dxsummit_irc_line(line, received_at=received_at)
            if spot is not None:
                with self._lock:
                    self._cache[spot.stable_key] = spot
                    self._last_spot_at = received_at
                    self._prune_cache_locked(received_at)

        return live_started_monotonic

    def _prune_cache_locked(self, now: datetime) -> None:
        cutoff = now - self._max_spot_age
        self._cache = {
            key: spot
            for key, spot in self._cache.items()
            if spot.spotted_at >= cutoff
        }
        if len(self._cache) <= self._max_spots:
            return

        newest = sorted(
            self._cache.values(),
            key=lambda spot: (spot.spotted_at, spot.stable_key),
            reverse=True,
        )[: self._max_spots]
        self._cache = {spot.stable_key: spot for spot in newest}

    def _record_disconnect(self, error: BaseException) -> None:
        text = (str(error).strip() or error.__class__.__name__)[:500]
        with self._lock:
            self._last_error = text
            self._state = DxSummitConnectionState.DISCONNECTED
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

    def _set_state(self, state: DxSummitConnectionState) -> None:
        with self._lock:
            self._state = state

    def _aware_now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("DX Summit provider clock must return an aware datetime.")
        return value.astimezone(UTC)

    def _fallback_nickname(self, attempt: int) -> str:
        suffix = "-RT" if attempt == 1 else f"-RT{attempt}"
        available = max(1, 20 - len(suffix))
        return self._nickname[:available] + suffix
