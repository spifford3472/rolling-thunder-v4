"""Background directory polling with bounded, expiring no-I/O friend status."""

from collections.abc import Callable
from concurrent.futures import Executor, ThreadPoolExecutor
from json import dumps
from threading import RLock
from time import monotonic
from urllib.parse import urlparse

from rolling_thunder.http_home_platform import HttpTransport, UrllibHttpTransport
from rolling_thunder.known_callsigns import (
    KnownCallsignBatch,
    KnownCallsignLookup,
    KnownCallsignSnapshot,
)
from rolling_thunder.radio_polling import PollScheduler, ScheduledPoll


class KnownCallsignClientError(OSError):
    """Directory lookup failed; callers must omit friend decoration."""


class HttpKnownCallsignClient:
    """Provider-independent snapshot/batch transport, for worker use only."""

    def __init__(
        self, base_url: str, *, timeout_s: float = 5, transport: HttpTransport | None = None
    ) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or timeout_s <= 0:
            raise ValueError("Known-callsign client requires an HTTP(S) URL and positive timeout")
        self._url = base_url.rstrip("/") + "/api/v1/known-callsigns"
        self._timeout = timeout_s
        self._transport = transport or UrllibHttpTransport()

    def _request(self, body: bytes | None) -> bytes:
        try:
            response = self._transport.request(
                "GET" if body is None else "POST",
                self._url,
                headers={"Accept": "application/json", "Content-Type": "application/json"},
                body=body,
                timeout_s=self._timeout,
            )
            if response.status_code != 200 or len(response.body) > 524_288:
                raise KnownCallsignClientError("Known-callsign response unavailable or oversized")
            return response.body
        except OSError as error:
            raise KnownCallsignClientError("Known-callsign service unavailable") from error

    def snapshot(self) -> KnownCallsignSnapshot:
        try:
            return KnownCallsignSnapshot.model_validate_json(self._request(None))
        except ValueError as error:
            raise KnownCallsignClientError("Invalid known-callsign snapshot") from error

    def lookup(self, callsigns: tuple[str, ...]) -> KnownCallsignLookup:
        request = KnownCallsignBatch(callsigns=callsigns)
        try:
            result = KnownCallsignLookup.model_validate_json(
                self._request(dumps(request.model_dump(mode="json")).encode())
            )
            if tuple(item.callsign for item in result.results) != tuple(
                dict.fromkeys(request.callsigns)
            ):
                raise ValueError("Batch response callsigns do not match request")
            return result
        except ValueError as error:
            raise KnownCallsignClientError("Invalid known-callsign batch response") from error


class KnownCallsignCache:
    """Immutable bounded classification, cleared on error and expired when stale."""

    def __init__(
        self,
        client: HttpKnownCallsignClient,
        *,
        stale_after_s: float = 90,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if stale_after_s <= 0:
            raise ValueError("Known-callsign staleness must be positive")
        self._client = client
        self._clock = clock
        self._ttl = stale_after_s
        self._lock = RLock()
        self._friends: frozenset[str] = frozenset()
        self._expires = 0.0
        self._error: str | None = None

    @property
    def friends(self) -> frozenset[str]:
        """Read published data only; never performs network I/O."""
        with self._lock:
            return self._friends if self._clock() < self._expires else frozenset()

    @property
    def error(self) -> str | None:
        with self._lock:
            return self._error

    def clear(self) -> None:
        with self._lock:
            self._friends = frozenset()
            self._expires = 0

    def refresh(self) -> None:
        try:
            result = self._client.snapshot()
        except (OSError, ValueError) as error:
            with self._lock:
                self._friends = frozenset()
                self._expires = 0
                self._error = str(error)
            return
        with self._lock:
            self._friends = frozenset(item.callsign for item in result.entries)
            self._expires = self._clock() + self._ttl
            self._error = None


class KnownCallsignPollingService:
    """One scheduled worker, independent of UI refreshes and provider lookups."""

    def __init__(
        self,
        cache: KnownCallsignCache,
        scheduler: PollScheduler,
        *,
        interval_s: float = 30,
        executor_factory: Callable[[], Executor] | None = None,
    ) -> None:
        if interval_s <= 0:
            raise ValueError("Known-callsign polling interval must be positive")
        self.cache = cache
        self._scheduler = scheduler
        self._interval = interval_s
        self._factory = executor_factory or (
            lambda: ThreadPoolExecutor(max_workers=1, thread_name_prefix="known-callsigns")
        )
        self._lock = RLock()
        self._executor: Executor | None = None
        self._scheduled: ScheduledPoll | None = None
        self._pending = False

    def start(self) -> None:
        with self._lock:
            if self._executor is not None:
                raise RuntimeError("Known-callsign polling already started")
            executor = self._factory()
            try:
                self._scheduled = self._scheduler.schedule_repeating(self._interval, self._queue)
            except Exception:
                executor.shutdown(wait=False, cancel_futures=True)
                raise
            self._executor = executor
        self._queue()

    def stop(self) -> None:
        with self._lock:
            executor, scheduled = self._executor, self._scheduled
            self._executor = None
            self._scheduled = None
        if scheduled is not None:
            scheduled.cancel()
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)
        with self._lock:
            self._pending = False
        self.cache.clear()

    def _queue(self) -> None:
        with self._lock:
            if self._executor is None or self._pending:
                return
            self._pending = True
            try:
                self._executor.submit(self._refresh)
            except Exception:
                self._pending = False
                raise

    def _refresh(self) -> None:
        try:
            self.cache.refresh()
        finally:
            with self._lock:
                self._pending = False
