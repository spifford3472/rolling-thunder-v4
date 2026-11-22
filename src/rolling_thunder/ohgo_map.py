"""Pi-side GPS gate and bounded background polling for the private OHGO feed."""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Lock
from urllib.request import Request, urlopen

from rolling_thunder.gps import GPSState
from rolling_thunder.live_map import GeoPoint, LiveMapPresentation, valid_map_position
from rolling_thunder.local_jurisdiction import (
    JURISDICTION_ARTIFACT_PATH,
    LocalJurisdictionResolver,
)
from rolling_thunder.ohgo_layers import (
    MAX_OHGO_FEED_BYTES,
    OHGO_LAYERS_PATH,
    OhgoLayer,
    OhgoLayersSnapshot,
    OhgoLayerStatus,
    decode_ohgo_layers,
)


def ohio_state_resolver() -> Callable[[GeoPoint], str | None]:
    """Create a lazy worker-owned resolver using the station jurisdiction artifact."""
    resolver: LocalJurisdictionResolver | None = None

    def resolve(point: GeoPoint) -> str | None:
        nonlocal resolver
        if resolver is None:
            resolver = LocalJurisdictionResolver.from_artifact(JURISDICTION_ARTIFACT_PATH)
        jurisdiction = resolver.resolve(point.latitude, point.longitude)
        return jurisdiction.state if jurisdiction is not None else None

    return resolve


def fetch_ohgo_map_layers(base_url: str) -> OhgoLayersSnapshot:
    request = Request(base_url.rstrip("/") + OHGO_LAYERS_PATH, headers={"Accept": "application/json"})
    with urlopen(request, timeout=2.0) as response:
        if response.status != 200:
            raise ValueError("OHGO map feed unavailable")
        return decode_ohgo_layers(response.read(MAX_OHGO_FEED_BYTES + 1))


class OhgoMapOverlay:
    """Consume current map GPS and publish immutable state without I/O on Tk."""

    def __init__(
        self,
        forge_url: str | None,
        resolve_state: Callable[[GeoPoint], str | None],
        *,
        gps_max_age: timedelta = timedelta(seconds=10),
        fetch: Callable[[str], OhgoLayersSnapshot] = fetch_ohgo_map_layers,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._url = forge_url
        self._gps_max_age = gps_max_age
        self._lock = Lock()
        self._tracking = False
        self._resolve_state = resolve_state
        self._fetch = fetch
        self._clock = clock
        self._monotonic = monotonic
        self._jurisdiction_worker = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="ohgo-jurisdiction"
        )
        self._feed_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ohgo-map")
        self._pending_state: Future[str | None] | None = None
        self._requested_point: GeoPoint | None = None
        self._resolved_point: GeoPoint | None = None
        self._resolved_state: str | None = None
        self._pending_feed: Future[OhgoLayersSnapshot] | None = None
        self._feed: OhgoLayersSnapshot = ()
        self._due = 0.0
        self._stopped = False

    def update(
        self,
        gps: LiveMapPresentation,
        enabled: frozenset[OhgoLayer],
    ) -> OhgoLayersSnapshot:
        """Advance bounded background work and return only enabled, fresh Ohio data."""
        now = self._clock()
        with self._lock:
            url = self._url
            self._tracking = bool(enabled and url and not self._stopped)
            if not self._tracking or not url:
                return ()
            point = (
                gps.position
                if gps.is_current and self._fresh_fix(gps.fix_time, now)
                else None
            )
            if not self._in_ohio(point):
                return ()
            return self._update_feed(url, enabled, now)

    def _fresh_fix(self, fix_time: datetime | None, now: datetime) -> bool:
        return fix_time is not None and timedelta(0) <= now - fix_time <= self._gps_max_age

    def observe_gps_state(self, state: GPSState) -> None:
        """Queue a new fix as soon as GPS publishes it, without resolving on that thread."""
        with self._lock:
            if not self._tracking:
                return
            accepted = valid_map_position(state)
            if accepted is not None and self._fresh_fix(accepted[1], self._clock()):
                self._in_ohio(accepted[0])

    def _update_feed(
        self, url: str, enabled: frozenset[OhgoLayer], now: datetime
    ) -> OhgoLayersSnapshot:
        if self._pending_feed is not None and self._pending_feed.done():
            try:
                self._feed = self._pending_feed.result()
            except (OSError, ValueError, TypeError, RecursionError):
                # Keep only age-eligible provider data through a transient Forge outage.
                pass
            self._pending_feed = None
        monotonic = self._monotonic()
        if self._pending_feed is None and monotonic >= self._due:
            self._pending_feed = self._feed_worker.submit(self._fetch, url)
            self._due = monotonic + 30
        return tuple(
            current
            for snapshot in self._feed
            if snapshot.layer in enabled
            and (current := snapshot.at(now)).status is OhgoLayerStatus.CURRENT
            and current.markers
        )

    def _in_ohio(self, point: GeoPoint | None) -> bool:
        if self._pending_state is not None and self._pending_state.done():
            self._resolved_point = self._requested_point
            try:
                self._resolved_state = self._pending_state.result()
            except (OSError, ValueError, TypeError):
                self._resolved_state = None
            self._pending_state = None
        if point is None:
            return False
        if point == self._resolved_point:
            return self._resolved_state == "OH"
        if self._pending_state is None:
            self._requested_point = point
            self._pending_state = self._jurisdiction_worker.submit(self._resolve_state, point)
        return False

    def stop(self) -> None:
        """Stop scheduling work and cancel any queued requests during cleanup."""
        with self._lock:
            self._stopped = True
            self._tracking = False
            self._jurisdiction_worker.shutdown(wait=False, cancel_futures=True)
            self._feed_worker.shutdown(wait=False, cancel_futures=True)
