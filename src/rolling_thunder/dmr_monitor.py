"""Background DMR hotspot monitoring without UI-thread network or SSH work."""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from threading import Event, Lock, Thread, current_thread
from typing import Protocol
from urllib.error import URLError
from urllib.request import Request, urlopen

from rolling_thunder.dmr_activity import DmrCallSnapshot, DmrLiveCallTracker, parse_mmdvm_dmr_line
from rolling_thunder.dmr_wpsd import (
    WpsdDmrHistoryRecord,
    WpsdPayloadError,
    WpsdRadioInfo,
    parse_wpsd_dmr_history,
    parse_wpsd_radio_info,
)


class DmrMonitorHealth(StrEnum):
    """Overall availability of the independent DMR monitor sources."""

    STARTING = "starting"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class DmrSourceError(RuntimeError):
    """Raised when a DMR transport cannot provide its requested data."""


@dataclass(frozen=True, slots=True)
class DmrMonitorSnapshot:
    """Immutable DMR state safe for synchronous UI reads."""

    active_calls: tuple[DmrCallSnapshot, ...] = ()
    history: tuple[WpsdDmrHistoryRecord, ...] = ()
    radio_info: WpsdRadioInfo | None = None
    live_available: bool = False
    history_available: bool = False
    radio_available: bool = False
    health: DmrMonitorHealth = DmrMonitorHealth.STARTING
    updated_at: datetime | None = None
    live_error: str | None = None
    history_error: str | None = None
    radio_error: str | None = None


class DmrLiveLineSource(Protocol):
    """Persistent line-oriented MMDVMHost event source."""

    def stream(self, stop_event: Event) -> Iterator[str]:
        """Yield live feed lines until stopped or the transport fails."""
        ...

    def close(self) -> None:
        """Interrupt any blocking live-feed read."""
        ...


class DmrWpsdSource(Protocol):
    """Synchronous WPSD reads invoked only by the monitor worker thread."""

    def fetch_history(self) -> tuple[WpsdDmrHistoryRecord, ...]:
        """Return the current normalized WPSD DMR history."""
        ...

    def fetch_radio_info(self) -> WpsdRadioInfo:
        """Return the current hotspot RF configuration."""
        ...


class SshDmrLiveLineSource:
    """Read the restricted Rolling Thunder MMDVM feed over OpenSSH."""

    def __init__(
        self,
        *,
        host: str,
        user: str,
        private_key: Path,
        connect_timeout_s: int = 5,
    ) -> None:
        if not host.strip() or not user.strip():
            raise ValueError("DMR SSH host and user must not be blank.")
        if connect_timeout_s <= 0:
            raise ValueError("DMR SSH connect timeout must be positive.")
        self._host = host.strip()
        self._user = user.strip()
        self._private_key = private_key
        self._connect_timeout_s = connect_timeout_s
        self._lock = Lock()
        self._process: subprocess.Popen[str] | None = None

    def stream(self, stop_event: Event) -> Iterator[str]:
        """Open the forced-command SSH feed and yield each remote output line."""
        command = [
            "ssh",
            "-T",
            "-n",
            "-i",
            str(self._private_key),
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "BatchMode=yes",
            "-o",
            f"ConnectTimeout={self._connect_timeout_s}",
            "-o",
            "ServerAliveInterval=5",
            "-o",
            "ServerAliveCountMax=2",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "LogLevel=ERROR",
            f"{self._user}@{self._host}",
        ]
        try:
            process = subprocess.Popen(  # noqa: S603
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except OSError as error:
            raise DmrSourceError(f"Could not start DMR SSH feed: {error}") from error

        with self._lock:
            self._process = process

        try:
            stdout = process.stdout
            if stdout is None:
                raise DmrSourceError("DMR SSH feed did not expose stdout.")

            for line in stdout:
                if stop_event.is_set():
                    break
                yield line.rstrip("\n")

            return_code = process.wait()
            if not stop_event.is_set() and return_code != 0:
                raise DmrSourceError(f"DMR SSH feed exited with status {return_code}.")
        finally:
            with self._lock:
                if self._process is process:
                    self._process = None
            if process.poll() is None:
                process.terminate()

    def close(self) -> None:
        """Terminate the active ssh process so a blocking stdout read wakes immediately."""
        with self._lock:
            process = self._process
        if process is not None and process.poll() is None:
            process.terminate()


class WpsdDmrHttpSource:
    """Read WPSD history and radio-info endpoints with bounded HTTP timeouts."""

    def __init__(
        self,
        *,
        base_url: str,
        timeout_s: float = 5.0,
        history_limit: int = 20,
    ) -> None:
        normalized = base_url.strip().rstrip("/")
        if not normalized:
            raise ValueError("WPSD base URL must not be blank.")
        if timeout_s <= 0:
            raise ValueError("WPSD HTTP timeout must be positive.")
        if history_limit < 1 or history_limit > 100:
            raise ValueError("WPSD history limit must be between 1 and 100.")
        self._base_url = normalized
        self._timeout_s = timeout_s
        self._history_limit = history_limit

    def fetch_history(self) -> tuple[WpsdDmrHistoryRecord, ...]:
        """Fetch and parse the supported WPSD JSON history endpoint."""
        payload = self._fetch(
            f"/api/?limit={self._history_limit}&names=true&country=true"
        )
        return parse_wpsd_dmr_history(payload)

    def fetch_radio_info(self) -> WpsdRadioInfo:
        """Fetch and parse WPSD radioinfo.php."""
        payload = self._fetch("/mmdvmhost/radioinfo.php")
        return parse_wpsd_radio_info(payload.decode("utf-8", errors="replace"))

    def _fetch(self, path: str) -> bytes:
        request = Request(
            f"{self._base_url}{path}",
            headers={"User-Agent": "RollingThunder-v4"},
        )
        try:
            with urlopen(request, timeout=self._timeout_s) as response:  # noqa: S310
                return response.read()
        except (OSError, TimeoutError, URLError) as error:
            raise DmrSourceError(f"WPSD request failed for {path}: {error}") from error


class DmrMonitorService:
    """Own live SSH and WPSD HTTP work on background threads."""

    def __init__(
        self,
        live_source: DmrLiveLineSource,
        wpsd_source: DmrWpsdSource,
        *,
        history_refresh_interval_s: float = 2.0,
        reconnect_delay_s: float = 2.0,
    ) -> None:
        if history_refresh_interval_s <= 0:
            raise ValueError("DMR history refresh interval must be positive.")
        if reconnect_delay_s <= 0:
            raise ValueError("DMR reconnect delay must be positive.")
        self._live_source = live_source
        self._wpsd_source = wpsd_source
        self._history_refresh_interval_s = history_refresh_interval_s
        self._reconnect_delay_s = reconnect_delay_s
        self._lock = Lock()
        self._stop_event = Event()
        self._snapshot = DmrMonitorSnapshot()
        self._live_thread: Thread | None = None
        self._wpsd_thread: Thread | None = None

    @property
    def latest_state(self) -> DmrMonitorSnapshot:
        """Return the latest immutable snapshot without any external I/O."""
        with self._lock:
            return self._snapshot

    @property
    def is_running(self) -> bool:
        """Return whether monitor workers are currently owned by the service."""
        with self._lock:
            return self._live_thread is not None or self._wpsd_thread is not None

    def start(self) -> DmrMonitorSnapshot:
        """Start both background workers without performing SSH or HTTP on the caller."""
        with self._lock:
            if self._live_thread is not None or self._wpsd_thread is not None:
                raise RuntimeError("DMR monitor service is already running.")
            self._stop_event.clear()
            self._snapshot = DmrMonitorSnapshot(health=DmrMonitorHealth.STARTING)
            live_thread = Thread(
                target=self._run_live,
                name="rolling-thunder-dmr-live",
                daemon=True,
            )
            wpsd_thread = Thread(
                target=self._run_wpsd,
                name="rolling-thunder-dmr-wpsd",
                daemon=True,
            )
            self._live_thread = live_thread
            self._wpsd_thread = wpsd_thread

        live_thread.start()
        wpsd_thread.start()
        return self.latest_state

    def stop(self) -> DmrMonitorSnapshot:
        """Stop both background workers and interrupt a blocking SSH feed."""
        self._stop_event.set()
        self._live_source.close()
        with self._lock:
            live_thread = self._live_thread
            wpsd_thread = self._wpsd_thread
            self._live_thread = None
            self._wpsd_thread = None

        for thread in (live_thread, wpsd_thread):
            if thread is not None and current_thread() is not thread:
                thread.join(timeout=max(self._history_refresh_interval_s, 2.0) + 1.0)
        return self.latest_state

    def _run_live(self) -> None:
        tracker = DmrLiveCallTracker()
        while not self._stop_event.is_set():
            try:
                for line in self._live_source.stream(self._stop_event):
                    if self._stop_event.is_set():
                        return
                    if line.startswith("RTDMR READY"):
                        self._publish_live(available=True, active_calls=tracker.active_calls, error=None)
                        continue
                    event = parse_mmdvm_dmr_line(line)
                    if event is None:
                        continue
                    tracker.apply(event)
                    self._publish_live(
                        available=True,
                        active_calls=tracker.active_calls,
                        error=None,
                    )
                if self._stop_event.is_set():
                    return
                tracker = DmrLiveCallTracker()
                self._publish_live(
                    available=False,
                    active_calls=(),
                    error="DMR live feed ended.",
                )
            except (DmrSourceError, OSError) as error:
                tracker = DmrLiveCallTracker()
                self._publish_live(
                    available=False,
                    active_calls=(),
                    error=str(error) or error.__class__.__name__,
                )

            if self._stop_event.wait(self._reconnect_delay_s):
                return

    def _run_wpsd(self) -> None:
        while not self._stop_event.is_set():
            self._refresh_history()
            if self._stop_event.is_set():
                return
            self._refresh_radio_info()
            if self._stop_event.wait(self._history_refresh_interval_s):
                return

    def _refresh_history(self) -> None:
        try:
            history = self._wpsd_source.fetch_history()
        except (DmrSourceError, WpsdPayloadError, OSError) as error:
            self._publish_history(
                available=False,
                history=None,
                error=str(error) or error.__class__.__name__,
            )
            return
        self._publish_history(available=True, history=history, error=None)

    def _refresh_radio_info(self) -> None:
        try:
            radio_info = self._wpsd_source.fetch_radio_info()
        except (DmrSourceError, WpsdPayloadError, OSError) as error:
            self._publish_radio(available=False, radio_info=None, error=str(error) or error.__class__.__name__)
            return
        self._publish_radio(available=True, radio_info=radio_info, error=None)

    @staticmethod
    def _health(live: bool, history: bool, radio: bool) -> DmrMonitorHealth:
        available_count = sum((live, history, radio))
        if available_count == 3:
            return DmrMonitorHealth.HEALTHY
        if available_count:
            return DmrMonitorHealth.DEGRADED
        return DmrMonitorHealth.UNAVAILABLE

    def _publish_live(
        self,
        *,
        available: bool,
        active_calls: tuple[DmrCallSnapshot, ...],
        error: str | None,
    ) -> None:
        with self._lock:
            current = self._snapshot
            self._snapshot = DmrMonitorSnapshot(
                active_calls=active_calls,
                history=current.history,
                radio_info=current.radio_info,
                live_available=available,
                history_available=current.history_available,
                radio_available=current.radio_available,
                health=self._health(
                    available,
                    current.history_available,
                    current.radio_available,
                ),
                updated_at=datetime.now(UTC),
                live_error=error,
                history_error=current.history_error,
                radio_error=current.radio_error,
            )

    def _publish_history(
        self,
        *,
        available: bool,
        history: tuple[WpsdDmrHistoryRecord, ...] | None,
        error: str | None,
    ) -> None:
        with self._lock:
            current = self._snapshot
            self._snapshot = DmrMonitorSnapshot(
                active_calls=current.active_calls,
                history=current.history if history is None else history,
                radio_info=current.radio_info,
                live_available=current.live_available,
                history_available=available,
                radio_available=current.radio_available,
                health=self._health(
                    current.live_available,
                    available,
                    current.radio_available,
                ),
                updated_at=datetime.now(UTC),
                live_error=current.live_error,
                history_error=error,
                radio_error=current.radio_error,
            )

    def _publish_radio(
        self,
        *,
        available: bool,
        radio_info: WpsdRadioInfo | None,
        error: str | None,
    ) -> None:
        with self._lock:
            current = self._snapshot
            self._snapshot = DmrMonitorSnapshot(
                active_calls=current.active_calls,
                history=current.history,
                radio_info=current.radio_info if radio_info is None else radio_info,
                live_available=current.live_available,
                history_available=current.history_available,
                radio_available=available,
                health=self._health(
                    current.live_available,
                    current.history_available,
                    available,
                ),
                updated_at=datetime.now(UTC),
                live_error=current.live_error,
                history_error=current.history_error,
                radio_error=error,
            )
