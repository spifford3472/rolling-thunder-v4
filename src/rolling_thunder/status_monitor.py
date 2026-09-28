"""Background health probes for glanceable vehicle status indicators."""

from __future__ import annotations

import ipaddress
import re
import socket
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from json import JSONDecodeError, loads
from pathlib import Path
from threading import Lock
from urllib.error import URLError
from urllib.parse import urlparse

from rolling_thunder.config import ApplicationConfig
from rolling_thunder.http_home_platform import HttpTransport, UrllibHttpTransport
from rolling_thunder.radio_polling import PollScheduler, ScheduledPoll
from rolling_thunder.threading_scheduler import ThreadingPollScheduler

_DEFAULT_POLL_INTERVAL_S = 15.0
_DEFAULT_INTERNET_ADDRESS = "8.8.8.8"
_DEFAULT_INTERNET_PORT = 53
_DEFAULT_INTERNET_TIMEOUT_S = 2.0
_INTERNET_FAILURE_THRESHOLD = 2
_ALSA_CAPTURE_COUNT = re.compile(r"\bcapture\s+(?P<count>\d+)\b", re.IGNORECASE)
_ALSA_CARD = re.compile(r"^\s*(?P<index>\d+)\s+\[(?P<name>[^]]+)\]")
_ALSA_DEVICE = re.compile(
    r"^(?:plug)?hw:CARD=(?P<card>[^,]+),DEV=(?P<device>\d+)$",
    re.IGNORECASE,
)


class StatusState(StrEnum):
    """Stable status states rendered by the vehicle icon strip."""

    STARTING = "starting"
    HEALTHY = "healthy"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """One immutable result produced by a bounded background probe."""

    state: StatusState = StatusState.STARTING
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class StatusMonitorSnapshot:
    """Latest non-radio health results safe for synchronous UI reads."""

    internet: ProbeResult = ProbeResult()
    forge: ProbeResult = ProbeResult()
    microphone: ProbeResult = ProbeResult()


class StatusProbe:
    """Small synchronous probe boundary executed only by the monitor worker."""

    def check(self) -> ProbeResult:
        """Perform one bounded check and return an immutable result."""
        raise NotImplementedError


def _connect_tcp(address: tuple[str, int], timeout_s: float) -> socket.socket:
    return socket.create_connection(address, timeout=timeout_s)


class InternetReachabilityProbe(StatusProbe):
    """Check direct-IP external TCP reachability without relying on DNS."""

    def __init__(
        self,
        *,
        host: str = _DEFAULT_INTERNET_ADDRESS,
        port: int = _DEFAULT_INTERNET_PORT,
        timeout_s: float = _DEFAULT_INTERNET_TIMEOUT_S,
        connector: Callable[[tuple[str, int], float], socket.socket] = _connect_tcp,
    ) -> None:
        ipaddress.ip_address(host)
        if not 1 <= port <= 65_535:
            raise ValueError("Internet probe port must be between 1 and 65535.")
        if timeout_s <= 0:
            raise ValueError("Internet probe timeout must be positive.")
        self._host = host
        self._port = port
        self._timeout_s = timeout_s
        self._connector = connector

    def check(self) -> ProbeResult:
        try:
            connection = self._connector((self._host, self._port), self._timeout_s)
        except (OSError, TimeoutError) as error:
            return ProbeResult(StatusState.UNAVAILABLE, str(error) or error.__class__.__name__)
        try:
            return ProbeResult(StatusState.HEALTHY)
        finally:
            connection.close()


class ForgeHealthProbe(StatusProbe):
    """Validate the existing Forge ``/api/v1/health`` endpoint."""

    def __init__(
        self,
        api_url: str,
        *,
        timeout_s: float,
        transport: HttpTransport | None = None,
    ) -> None:
        normalized = api_url.strip().rstrip("/")
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Forge status API URL must be an absolute HTTP or HTTPS URL.")
        if timeout_s <= 0:
            raise ValueError("Forge status timeout must be positive.")
        self._url = f"{normalized}/api/v1/health"
        self._timeout_s = timeout_s
        self._transport = transport or UrllibHttpTransport()

    def check(self) -> ProbeResult:
        try:
            response = self._transport.request(
                "GET",
                self._url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "RollingThunder-v4",
                },
                body=None,
                timeout_s=self._timeout_s,
            )
        except (OSError, TimeoutError, URLError) as error:
            return ProbeResult(StatusState.UNAVAILABLE, str(error) or error.__class__.__name__)

        if not 200 <= response.status_code < 300:
            return ProbeResult(
                StatusState.UNAVAILABLE,
                f"Forge health returned HTTP {response.status_code}",
            )

        try:
            payload = loads(response.body)
        except (JSONDecodeError, UnicodeDecodeError) as error:
            return ProbeResult(StatusState.UNAVAILABLE, f"Invalid Forge health JSON: {error}")
        if not isinstance(payload, dict):
            return ProbeResult(StatusState.UNAVAILABLE, "Forge health JSON root is not an object")

        service_status = payload.get("service_status")
        if service_status == "healthy":
            return ProbeResult(StatusState.HEALTHY)
        if service_status == "starting":
            return ProbeResult(StatusState.STARTING, "Forge is starting")
        if isinstance(service_status, str):
            return ProbeResult(StatusState.UNAVAILABLE, f"Forge is {service_status}")
        return ProbeResult(StatusState.UNAVAILABLE, "Forge health omitted service_status")


class AlsaCaptureProbe(StatusProbe):
    """Check configured ALSA capture enumeration without opening the microphone."""

    def __init__(
        self,
        audio_device: str,
        *,
        cards_reader: Callable[[], str] | None = None,
        pcm_reader: Callable[[], str] | None = None,
    ) -> None:
        normalized = audio_device.strip()
        if not normalized:
            raise ValueError("Microphone ALSA device must not be blank.")
        self._audio_device = normalized
        self._cards_reader = cards_reader or self._read_cards
        self._pcm_reader = pcm_reader or self._read_pcm

    @staticmethod
    def _read_cards() -> str:
        return Path("/proc/asound/cards").read_text(encoding="utf-8")

    @staticmethod
    def _read_pcm() -> str:
        return Path("/proc/asound/pcm").read_text(encoding="utf-8")

    def check(self) -> ProbeResult:
        try:
            cards = self._cards_reader()
            pcm = self._pcm_reader()
        except OSError as error:
            return ProbeResult(StatusState.UNAVAILABLE, str(error) or error.__class__.__name__)

        if self._audio_device.lower() == "default":
            return (
                ProbeResult(StatusState.HEALTHY)
                if self._has_any_capture(pcm)
                else ProbeResult(StatusState.UNAVAILABLE, "No ALSA capture PCM is enumerated")
            )

        match = _ALSA_DEVICE.fullmatch(self._audio_device)
        if match is None:
            return ProbeResult(
                StatusState.UNAVAILABLE,
                f"Unsupported ALSA capture selector: {self._audio_device}",
            )

        card_index = self._resolve_card_index(cards, match.group("card"))
        if card_index is None:
            return ProbeResult(
                StatusState.UNAVAILABLE,
                f"ALSA card {match.group('card')} is not present",
            )

        device_index = int(match.group("device"))
        prefix = f"{card_index:02d}-{device_index:02d}:"
        for line in pcm.splitlines():
            if line.lstrip().startswith(prefix) and self._capture_count(line) > 0:
                return ProbeResult(StatusState.HEALTHY)
        return ProbeResult(
            StatusState.UNAVAILABLE,
            f"ALSA capture PCM {card_index},{device_index} is not present",
        )

    @staticmethod
    def _resolve_card_index(cards: str, configured_card: str) -> int | None:
        if configured_card.isdigit():
            wanted_index = int(configured_card)
            return wanted_index if any(
                match is not None and int(match.group("index")) == wanted_index
                for match in (_ALSA_CARD.match(line) for line in cards.splitlines())
            ) else None

        wanted_name = configured_card.casefold()
        for line in cards.splitlines():
            match = _ALSA_CARD.match(line)
            if match is not None and match.group("name").strip().casefold() == wanted_name:
                return int(match.group("index"))
        return None

    @classmethod
    def _has_any_capture(cls, pcm: str) -> bool:
        return any(cls._capture_count(line) > 0 for line in pcm.splitlines())

    @staticmethod
    def _capture_count(line: str) -> int:
        match = _ALSA_CAPTURE_COUNT.search(line)
        return 0 if match is None else int(match.group("count"))


class FixedStatusProbe(StatusProbe):
    """Return one constant result for a deliberately unavailable subsystem."""

    def __init__(self, result: ProbeResult) -> None:
        self._result = result

    def check(self) -> ProbeResult:
        return self._result


class StatusMonitorService:
    """Poll Internet, Forge, and microphone health outside the Tk thread."""

    def __init__(
        self,
        internet: StatusProbe,
        forge: StatusProbe,
        microphone: StatusProbe,
        scheduler: PollScheduler,
        *,
        interval_s: float = _DEFAULT_POLL_INTERVAL_S,
        internet_failure_threshold: int = _INTERNET_FAILURE_THRESHOLD,
    ) -> None:
        if interval_s <= 0:
            raise ValueError("Status monitor interval must be positive.")
        if internet_failure_threshold < 1:
            raise ValueError("Internet failure threshold must be positive.")
        self._internet = internet
        self._forge = forge
        self._microphone = microphone
        self._scheduler = scheduler
        self._interval_s = interval_s
        self._internet_failure_threshold = internet_failure_threshold
        self._lock = Lock()
        self._snapshot = StatusMonitorSnapshot()
        self._scheduled_poll: ScheduledPoll | None = None
        self._checking = False
        self._internet_failures = 0

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._scheduled_poll is not None

    @property
    def latest_state(self) -> StatusMonitorSnapshot:
        with self._lock:
            return self._snapshot

    def start(self) -> StatusMonitorSnapshot:
        """Schedule checks without performing network or device I/O on the caller."""
        with self._lock:
            if self._scheduled_poll is not None:
                raise RuntimeError("Status monitor service is already running.")
            self._scheduled_poll = self._scheduler.schedule_repeating(
                self._interval_s,
                self._check_once,
            )
            return self._snapshot

    def stop(self) -> StatusMonitorSnapshot:
        with self._lock:
            scheduled = self._scheduled_poll
            self._scheduled_poll = None
        if scheduled is not None:
            scheduled.cancel()
        return self.latest_state

    def check_now(self) -> StatusMonitorSnapshot:
        """Run one synchronous cycle for worker/manual-test use, never from Tk."""
        self._check_once(force=True)
        return self.latest_state

    def _check_once(self, *, force: bool = False) -> None:
        with self._lock:
            if self._checking or (self._scheduled_poll is None and not force):
                return
            self._checking = True
            previous = self._snapshot

        try:
            internet = self._stabilize_internet(
                self._safe_check(self._internet),
                previous.internet,
            )
            forge = self._safe_check(self._forge)
            microphone = self._safe_check(self._microphone)
            snapshot = StatusMonitorSnapshot(
                internet=internet,
                forge=forge,
                microphone=microphone,
            )
            with self._lock:
                self._snapshot = snapshot
        finally:
            with self._lock:
                self._checking = False

    def _stabilize_internet(
        self,
        result: ProbeResult,
        previous: ProbeResult,
    ) -> ProbeResult:
        if result.state is not StatusState.UNAVAILABLE:
            self._internet_failures = 0
            return result

        self._internet_failures += 1
        if (
            previous.state is StatusState.HEALTHY
            and self._internet_failures < self._internet_failure_threshold
        ):
            return previous
        return result

    @staticmethod
    def _safe_check(probe: StatusProbe) -> ProbeResult:
        try:
            return probe.check()
        except Exception as error:  # noqa: BLE001 - health boundary must never kill monitoring
            return ProbeResult(
                StatusState.UNAVAILABLE,
                str(error) or error.__class__.__name__,
            )


def build_status_monitor(
    config: ApplicationConfig,
    *,
    scheduler: PollScheduler | None = None,
    forge_transport: HttpTransport | None = None,
) -> StatusMonitorService:
    """Compose the production vehicle status monitor from existing configuration."""
    forge_probe: StatusProbe
    if config.forge.enabled and config.forge.api_url is not None:
        forge_probe = ForgeHealthProbe(
            str(config.forge.api_url),
            timeout_s=config.forge.request_timeout_s,
            transport=forge_transport,
        )
    else:
        forge_probe = FixedStatusProbe(
            ProbeResult(StatusState.UNAVAILABLE, "Forge is disabled")
        )

    microphone_probe: StatusProbe
    if config.speech.enabled:
        microphone_probe = AlsaCaptureProbe(config.speech.audio_device)
    else:
        microphone_probe = FixedStatusProbe(
            ProbeResult(StatusState.UNAVAILABLE, "Microphone capture is disabled")
        )

    return StatusMonitorService(
        InternetReachabilityProbe(),
        forge_probe,
        microphone_probe,
        scheduler or ThreadingPollScheduler(),
    )
