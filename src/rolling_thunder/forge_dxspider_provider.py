"""Bounded DXSpider snapshot-session adapter for the independent Forge service."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
import socket
from typing import Protocol

from rolling_thunder.forge_config import ForgeDxSpiderProviderConfig
from rolling_thunder.forge_dx_spot_parser import (
    DxSpotLineError,
    is_dx_spot_line,
    parse_dx_spot_line,
)
from rolling_thunder.forge_spot_provider import (
    ForgeProviderSlice,
    ForgeSpotProviderConnectionError,
    ForgeSpotProviderError,
    ForgeSpotProviderResponseError,
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


class DxSpiderSession(Protocol):
    """One bounded line-oriented connection to a DXSpider-compatible node."""

    def send_line(self, line: str) -> None:
        """Send one ASCII command line terminated for a telnet-style service."""
        ...

    def read(self, max_bytes: int) -> bytes:
        """Read up to max_bytes, returning empty bytes after orderly closure."""
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
        """Open a bounded session or raise a connection-related exception."""
        ...


class SocketDxSpiderSession:
    """Standard-library socket implementation of one DXSpider session."""

    def __init__(self, connection: socket.socket) -> None:
        self._connection = connection

    def send_line(self, line: str) -> None:
        """Send one ASCII command with CRLF termination."""
        self._connection.sendall(line.encode("ascii") + b"\r\n")

    def read(self, max_bytes: int) -> bytes:
        """Read one bounded response chunk."""
        return self._connection.recv(max_bytes)

    def close(self) -> None:
        """Close the underlying socket."""
        self._connection.close()


class SocketDxSpiderSessionFactory:
    """Production factory using a bounded standard-library TCP connection."""

    def open(
        self,
        *,
        host: str,
        port: int,
        connect_timeout_s: float,
        read_timeout_s: float,
    ) -> DxSpiderSession:
        """Open a TCP session and apply the configured read timeout."""
        try:
            connection = socket.create_connection(
                (host, port),
                timeout=connect_timeout_s,
            )
            connection.settimeout(read_timeout_s)
        except (TimeoutError, OSError) as error:
            raise ForgeSpotProviderConnectionError(
                "DXSpider connection could not be established."
            ) from error
        return SocketDxSpiderSession(connection)


class ForgeDxSpiderSpotProvider:
    """Fetch one complete bounded DX slice through a short-lived cluster session."""

    def __init__(
        self,
        config: ForgeDxSpiderProviderConfig,
        *,
        session_factory: DxSpiderSessionFactory | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._config = config
        self._session_factory = session_factory or SocketDxSpiderSessionFactory()
        self._clock = clock or (lambda: datetime.now(UTC))

    @property
    def provider(self) -> SpotProvider:
        """Return the shared DX provider family."""
        return SpotProvider.DX

    def fetch_slice(self) -> ForgeProviderSlice:
        """Fetch, normalize, age-filter, and canonicalize one complete DX slice."""
        fetched_at = self._normalized_clock_value()
        session = self._open_session()
        try:
            self._send_snapshot_commands(session)
            response = self._read_bounded_response(session)
        except ForgeSpotProviderError:
            raise
        except (TimeoutError, OSError) as error:
            raise ForgeSpotProviderConnectionError(
                "DXSpider snapshot session did not complete."
            ) from error
        finally:
            try:
                session.close()
            except OSError:
                pass

        spots = self._parse_response(response, fetched_at=fetched_at)
        return ForgeProviderSlice.from_spots(
            provider=self.provider,
            fetched_at=fetched_at,
            spots=spots,
        )

    def _normalized_clock_value(self) -> datetime:
        fetched_at = self._clock()
        if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
            raise ValueError("DXSpider provider clock must return an aware datetime.")
        return fetched_at.astimezone(UTC)

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

    def _send_snapshot_commands(self, session: DxSpiderSession) -> None:
        for line in (
            str(self._config.login_callsign),
            "set/page 0",
            "show/fdx",
            "bye",
        ):
            session.send_line(line)

    def _read_bounded_response(self, session: DxSpiderSession) -> bytes:
        response = bytearray()
        while True:
            remaining = self._config.max_response_bytes - len(response)
            requested = min(_READ_CHUNK_BYTES, remaining + 1)
            chunk = session.read(requested)
            if not chunk:
                break
            response.extend(chunk)
            if len(response) > self._config.max_response_bytes:
                raise ForgeSpotProviderResponseError(
                    "DXSpider response exceeded the configured byte limit."
                )

        if not response:
            raise ForgeSpotProviderResponseError(
                "DXSpider snapshot session returned an empty response."
            )
        return bytes(response)

    def _parse_response(
        self,
        response: bytes,
        *,
        fetched_at: datetime,
    ) -> tuple[SpotRecord, ...]:
        text = strip_telnet_negotiation(response).decode("utf-8", errors="replace")
        spot_like_count = 0
        parsed_count = 0
        accepted: list[SpotRecord] = []
        maximum_age = timedelta(seconds=self._config.max_spot_age_s)

        for line in text.splitlines():
            if not is_dx_spot_line(line):
                continue
            spot_like_count += 1
            try:
                spot = parse_dx_spot_line(line, fetched_at=fetched_at)
            except DxSpotLineError:
                continue
            parsed_count += 1

            if fetched_at - spot.spotted_at > maximum_age:
                continue
            accepted.append(spot)
            if len(accepted) >= self._config.max_spots:
                break

        if spot_like_count > 0 and parsed_count == 0:
            raise ForgeSpotProviderResponseError(
                "DXSpider response contained spot-like lines but no usable DX records."
            )
        return tuple(accepted)


def strip_telnet_negotiation(data: bytes) -> bytes:
    """Remove common telnet negotiation sequences from a complete response."""
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
