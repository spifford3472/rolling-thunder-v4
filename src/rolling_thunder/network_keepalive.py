"""Deterministic background keepalive for the mobile cellular network path."""

from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from rolling_thunder.domain import DomainModel
from rolling_thunder.radio_polling import PollScheduler, ScheduledPoll

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class NetworkKeepaliveAvailability(StrEnum):
    """Reachability state of the configured keepalive target."""

    UNKNOWN = "unknown"
    REACHABLE = "reachable"
    UNREACHABLE = "unreachable"


class NetworkKeepaliveState(DomainModel):
    """Immutable status from the most recent keepalive attempt."""

    availability: NetworkKeepaliveAvailability = NetworkKeepaliveAvailability.UNKNOWN
    checked_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None


class NetworkKeepaliveTransport(Protocol):
    """Minimal transport needed to generate outbound keepalive traffic."""

    def send(self, url: str, *, timeout_s: float) -> None:
        """Send one lightweight request or raise an exception."""
        ...


class UrllibNetworkKeepaliveTransport:
    """Standard-library HTTP transport using a HEAD request."""

    def send(self, url: str, *, timeout_s: float) -> None:
        request = Request(url, method="HEAD")
        try:
            with urlopen(request, timeout=timeout_s) as response:
                response.read(0)
        except HTTPError as error:
            raise OSError(f"HTTP {error.code}: {error.reason}") from error
        except URLError as error:
            raise OSError(str(error.reason)) from error
        except TimeoutError as error:
            raise OSError("request timed out") from error


class NetworkKeepaliveService:
    """Periodically generate minimal WAN traffic without blocking local work."""

    def __init__(
        self,
        target_url: str,
        scheduler: PollScheduler,
        *,
        interval_s: float = 30.0,
        timeout_s: float = 5.0,
        transport: NetworkKeepaliveTransport | None = None,
        clock: Clock = _utc_now,
    ) -> None:
        if not target_url.strip():
            raise ValueError("Network keepalive target URL must not be empty.")
        if interval_s <= 0:
            raise ValueError("Network keepalive interval must be positive.")
        if timeout_s <= 0:
            raise ValueError("Network keepalive timeout must be positive.")

        self._target_url = target_url
        self._scheduler = scheduler
        self._interval_s = interval_s
        self._timeout_s = timeout_s
        self._transport = transport or UrllibNetworkKeepaliveTransport()
        self._clock = clock
        self._scheduled_poll: ScheduledPoll | None = None
        self._sending = False
        self._latest_state = NetworkKeepaliveState()

    @property
    def is_running(self) -> bool:
        return self._scheduled_poll is not None

    @property
    def latest_state(self) -> NetworkKeepaliveState:
        return self._latest_state

    def start(self) -> NetworkKeepaliveState:
        """Schedule keepalives without performing startup network I/O."""
        if self.is_running:
            raise RuntimeError("Network keepalive service is already running.")
        self._scheduled_poll = self._scheduler.schedule_repeating(
            self._interval_s,
            self._send_once,
        )
        return self._latest_state

    def stop(self) -> NetworkKeepaliveState:
        scheduled_poll = self._scheduled_poll
        self._scheduled_poll = None
        if scheduled_poll is not None:
            scheduled_poll.cancel()
        return self._latest_state

    def send_now(self) -> NetworkKeepaliveState:
        if self._sending:
            return self._latest_state
        return self._run_once()

    def _send_once(self) -> None:
        if not self.is_running or self._sending:
            return
        self._run_once()

    def _run_once(self) -> NetworkKeepaliveState:
        self._sending = True
        checked_at = self._timestamp()
        try:
            self._transport.send(self._target_url, timeout_s=self._timeout_s)
        except OSError as error:
            self._latest_state = NetworkKeepaliveState(
                availability=NetworkKeepaliveAvailability.UNREACHABLE,
                checked_at=checked_at,
                last_success_at=self._latest_state.last_success_at,
                last_error=str(error),
            )
        else:
            self._latest_state = NetworkKeepaliveState(
                availability=NetworkKeepaliveAvailability.REACHABLE,
                checked_at=checked_at,
                last_success_at=checked_at,
                last_error=None,
            )
        finally:
            self._sending = False
        return self._latest_state

    def _timestamp(self) -> datetime:
        timestamp = self._clock()
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("Network keepalive clock must be timezone-aware.")
        return timestamp.astimezone(UTC)
