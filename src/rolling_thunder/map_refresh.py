"""Durable age-based refresh support for installed offline map tiles."""

from __future__ import annotations

import random
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from threading import Event, Lock, Thread
from time import monotonic, sleep
from typing import Protocol
from zoneinfo import ZoneInfo

from rolling_thunder.map_tiles import MapTileKey, validate_map_tile_png

Clock = Callable[[], datetime]
RandomSource = Callable[[], float]
MonotonicClock = Callable[[], float]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class MapRefreshStorageError(RuntimeError):
    """Raised when durable map refresh state cannot be read or updated."""


class MapRefreshReason(StrEnum):
    """Why an installed tile was considered for refresh."""

    DISPLAYED = "displayed"
    GPS = "gps"


class MapRefreshDecision(StrEnum):
    """Age-policy result for one installed tile observation."""

    NONE = "none"
    PROBABILISTIC = "probabilistic"
    REQUIRED = "required"


@dataclass(frozen=True, order=True, slots=True)
class MapRefreshKey:
    """Unique identity of one style-specific installed raster tile."""

    package_id: str
    style: str
    tile: MapTileKey

    def __post_init__(self) -> None:
        if not self.package_id.strip():
            raise ValueError("Map refresh package id must not be blank.")
        if not self.style.strip():
            raise ValueError("Map refresh style must not be blank.")


@dataclass(frozen=True, slots=True)
class RefreshedMapTile:
    """One validated mutable override for an immutable installed package tile."""

    png: bytes
    refreshed_at: datetime


@dataclass(frozen=True, slots=True)
class QueuedMapRefresh:
    """One durable refresh request waiting for the deferred processing window."""

    key: MapRefreshKey
    reason: MapRefreshReason
    required: bool
    requested_at: datetime
    attempts: int
    next_attempt_at: datetime


@dataclass(frozen=True, slots=True)
class MapRefreshPolicy:
    """Deterministic thresholds and bounded probabilistic refresh behavior."""

    fresh_for: timedelta = timedelta(days=30)
    required_after: timedelta = timedelta(days=365)
    eligible_probability: float = 0.10
    observation_cooldown: timedelta = timedelta(hours=6)

    def __post_init__(self) -> None:
        if self.fresh_for <= timedelta(0):
            raise ValueError("Map refresh fresh window must be positive.")
        if self.required_after <= self.fresh_for:
            raise ValueError("Required refresh age must exceed the fresh window.")
        if not 0.0 <= self.eligible_probability <= 1.0:
            raise ValueError("Map refresh probability must be between zero and one.")
        if self.observation_cooldown <= timedelta(0):
            raise ValueError("Map refresh observation cooldown must be positive.")

    def decide(
        self,
        refreshed_at: datetime,
        now: datetime,
        *,
        random_value: float,
    ) -> MapRefreshDecision:
        """Return the age decision without performing storage or network work."""
        refreshed = _aware_utc(refreshed_at, "Tile refresh timestamp")
        current = _aware_utc(now, "Map refresh clock")
        age = max(timedelta(0), current - refreshed)
        if age < self.fresh_for:
            return MapRefreshDecision.NONE
        if age > self.required_after:
            return MapRefreshDecision.REQUIRED
        if not 0.0 <= random_value <= 1.0:
            raise ValueError("Random refresh value must be between zero and one.")
        if random_value < self.eligible_probability:
            return MapRefreshDecision.PROBABILISTIC
        return MapRefreshDecision.NONE


class MapRefreshStore:
    """Small SQLite overlay and durable queue beside the large map cache."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._init_lock = Lock()
        self._initialized = False

    @property
    def path(self) -> Path:
        return self._path

    def read_override(self, key: MapRefreshKey) -> RefreshedMapTile | None:
        """Return a validated refreshed tile without creating missing storage."""
        if not self._path.exists():
            return None
        try:
            with sqlite3.connect(self._path) as connection:
                row = connection.execute(
                    """
                    SELECT png, refreshed_at_utc
                    FROM refreshed_map_tiles
                    WHERE package_id = ? AND style = ? AND zoom = ? AND x = ? AND y = ?
                    """,
                    _identity_values(key),
                ).fetchone()
        except sqlite3.Error as error:
            raise MapRefreshStorageError(f"Could not read map refresh overlay: {error}") from error
        if row is None:
            return None
        raw_png, raw_timestamp = row
        if not isinstance(raw_png, (bytes, bytearray, memoryview)):
            raise MapRefreshStorageError("Map refresh overlay contained non-binary tile data.")
        try:
            refreshed_at = _parse_timestamp(str(raw_timestamp))
            png = validate_map_tile_png(bytes(raw_png))
        except (ValueError, RuntimeError) as error:
            raise MapRefreshStorageError("Map refresh overlay contained invalid tile data.") from error
        return RefreshedMapTile(png=png, refreshed_at=refreshed_at)

    def contains_queued(self, key: MapRefreshKey) -> bool:
        if not self._path.exists():
            return False
        try:
            with sqlite3.connect(self._path) as connection:
                row = connection.execute(
                    """
                    SELECT 1 FROM map_refresh_queue
                    WHERE package_id = ? AND style = ? AND zoom = ? AND x = ? AND y = ?
                    """,
                    _identity_values(key),
                ).fetchone()
        except sqlite3.Error as error:
            raise MapRefreshStorageError(f"Could not inspect map refresh queue: {error}") from error
        return row is not None

    def enqueue(
        self,
        key: MapRefreshKey,
        *,
        reason: MapRefreshReason,
        required: bool,
        requested_at: datetime,
    ) -> bool:
        """Durably coalesce one refresh request; mandatory status may only upgrade."""
        now = _aware_utc(requested_at, "Refresh request timestamp")
        self._ensure_initialized()
        try:
            with sqlite3.connect(self._path) as connection:
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO map_refresh_queue (
                        package_id, style, zoom, x, y, reason, required,
                        requested_at_utc, attempts, next_attempt_at_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                    """,
                    (
                        *_identity_values(key),
                        reason.value,
                        int(required),
                        _timestamp_text(now),
                        _timestamp_text(now),
                    ),
                )
                inserted = cursor.rowcount == 1
                if required and not inserted:
                    connection.execute(
                        """
                        UPDATE map_refresh_queue
                        SET required = 1
                        WHERE package_id = ? AND style = ? AND zoom = ? AND x = ? AND y = ?
                        """,
                        _identity_values(key),
                    )
                connection.commit()
                return inserted
        except sqlite3.Error as error:
            raise MapRefreshStorageError(f"Could not enqueue map tile refresh: {error}") from error

    def pending(self, *, limit: int, now: datetime) -> tuple[QueuedMapRefresh, ...]:
        if limit < 1:
            raise ValueError("Map refresh batch limit must be positive.")
        current = _aware_utc(now, "Map refresh queue clock")
        if not self._path.exists():
            return ()
        try:
            with sqlite3.connect(self._path) as connection:
                rows = connection.execute(
                    """
                    SELECT package_id, style, zoom, x, y, reason, required,
                           requested_at_utc, attempts, next_attempt_at_utc
                    FROM map_refresh_queue
                    WHERE next_attempt_at_utc <= ?
                    ORDER BY required DESC, requested_at_utc ASC
                    LIMIT ?
                    """,
                    (_timestamp_text(current), limit),
                ).fetchall()
        except sqlite3.Error as error:
            raise MapRefreshStorageError(f"Could not read map refresh queue: {error}") from error
        result: list[QueuedMapRefresh] = []
        for row in rows:
            package_id, style, zoom, x, y, reason, required, requested, attempts, next_attempt = row
            result.append(
                QueuedMapRefresh(
                    key=MapRefreshKey(
                        package_id=str(package_id),
                        style=str(style),
                        tile=MapTileKey(zoom=int(zoom), x=int(x), y=int(y)),
                    ),
                    reason=MapRefreshReason(str(reason)),
                    required=bool(required),
                    requested_at=_parse_timestamp(str(requested)),
                    attempts=int(attempts),
                    next_attempt_at=_parse_timestamp(str(next_attempt)),
                )
            )
        return tuple(result)

    def complete(self, item: QueuedMapRefresh, png: bytes, *, refreshed_at: datetime) -> None:
        """Validate then atomically replace the overlay and remove queue work."""
        validated = validate_map_tile_png(png)
        timestamp = _aware_utc(refreshed_at, "Map refresh completion timestamp")
        self._ensure_initialized()
        try:
            with sqlite3.connect(self._path) as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    INSERT INTO refreshed_map_tiles (
                        package_id, style, zoom, x, y, png, refreshed_at_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(package_id, style, zoom, x, y) DO UPDATE SET
                        png = excluded.png,
                        refreshed_at_utc = excluded.refreshed_at_utc
                    """,
                    (*_identity_values(item.key), validated, _timestamp_text(timestamp)),
                )
                connection.execute(
                    """
                    DELETE FROM map_refresh_queue
                    WHERE package_id = ? AND style = ? AND zoom = ? AND x = ? AND y = ?
                    """,
                    _identity_values(item.key),
                )
                connection.commit()
        except sqlite3.Error as error:
            raise MapRefreshStorageError(f"Could not store refreshed map tile: {error}") from error

    def fail(self, item: QueuedMapRefresh, *, failed_at: datetime) -> None:
        """Retain failed work with capped exponential retry delay."""
        timestamp = _aware_utc(failed_at, "Map refresh failure timestamp")
        attempts = item.attempts + 1
        delay_minutes = min(360, 15 * (2 ** min(attempts - 1, 5)))
        next_attempt = timestamp + timedelta(minutes=delay_minutes)
        self._ensure_initialized()
        try:
            with sqlite3.connect(self._path) as connection:
                connection.execute(
                    """
                    UPDATE map_refresh_queue
                    SET attempts = ?, next_attempt_at_utc = ?
                    WHERE package_id = ? AND style = ? AND zoom = ? AND x = ? AND y = ?
                    """,
                    (
                        attempts,
                        _timestamp_text(next_attempt),
                        *_identity_values(item.key),
                    ),
                )
                connection.commit()
        except sqlite3.Error as error:
            raise MapRefreshStorageError(f"Could not retain failed map refresh: {error}") from error

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            parent = self._path.parent
            if not parent.exists():
                raise MapRefreshStorageError(
                    f"Map refresh storage parent is unavailable: {parent}"
                )
            try:
                with sqlite3.connect(self._path) as connection:
                    connection.executescript(
                        """
                        PRAGMA journal_mode=WAL;
                        CREATE TABLE IF NOT EXISTS refreshed_map_tiles (
                            package_id TEXT NOT NULL,
                            style TEXT NOT NULL,
                            zoom INTEGER NOT NULL,
                            x INTEGER NOT NULL,
                            y INTEGER NOT NULL,
                            png BLOB NOT NULL,
                            refreshed_at_utc TEXT NOT NULL,
                            PRIMARY KEY (package_id, style, zoom, x, y)
                        );
                        CREATE TABLE IF NOT EXISTS map_refresh_queue (
                            package_id TEXT NOT NULL,
                            style TEXT NOT NULL,
                            zoom INTEGER NOT NULL,
                            x INTEGER NOT NULL,
                            y INTEGER NOT NULL,
                            reason TEXT NOT NULL,
                            required INTEGER NOT NULL,
                            requested_at_utc TEXT NOT NULL,
                            attempts INTEGER NOT NULL,
                            next_attempt_at_utc TEXT NOT NULL,
                            PRIMARY KEY (package_id, style, zoom, x, y)
                        );
                        CREATE INDEX IF NOT EXISTS map_refresh_queue_due
                        ON map_refresh_queue(required DESC, next_attempt_at_utc, requested_at_utc);
                        """
                    )
            except sqlite3.Error as error:
                raise MapRefreshStorageError(
                    f"Could not initialize map refresh storage {self._path}: {error}"
                ) from error
            self._initialized = True


class MapRefreshCoordinator:
    """Apply age policy with in-memory observation throttling and durable dedup."""

    def __init__(
        self,
        store: MapRefreshStore,
        *,
        policy: MapRefreshPolicy = MapRefreshPolicy(),
        clock: Clock = _utc_now,
        random_source: RandomSource = random.random,
    ) -> None:
        self._store = store
        self._policy = policy
        self._clock = clock
        self._random = random_source
        self._lock = Lock()
        self._last_considered: dict[MapRefreshKey, datetime] = {}

    @property
    def store(self) -> MapRefreshStore:
        return self._store

    def observe(
        self,
        key: MapRefreshKey,
        *,
        refreshed_at: datetime,
        reason: MapRefreshReason,
    ) -> MapRefreshDecision:
        """Evaluate one used tile without delaying its already-completed render path."""
        now = _aware_utc(self._clock(), "Map refresh coordinator clock")
        with self._lock:
            last = self._last_considered.get(key)
            if last is not None and now - last < self._policy.observation_cooldown:
                return MapRefreshDecision.NONE
            self._last_considered[key] = now
        try:
            if self._store.contains_queued(key):
                return MapRefreshDecision.NONE
        except MapRefreshStorageError:
            return MapRefreshDecision.NONE
        decision = self._policy.decide(
            refreshed_at,
            now,
            random_value=self._random(),
        )
        if decision is MapRefreshDecision.NONE:
            return decision
        try:
            self._store.enqueue(
                key,
                reason=reason,
                required=decision is MapRefreshDecision.REQUIRED,
                requested_at=now,
            )
        except MapRefreshStorageError:
            return MapRefreshDecision.NONE
        return decision


class DeferredMapTileClient(Protocol):
    """Private Forge map client used only by the deferred refresh worker."""

    def refresh_health(self) -> tuple[bool, bool]:
        """Return internet-health and Forge-health availability."""

    def fetch_for_style(self, key: MapTileKey, style: str) -> bytes:
        """Fetch one validated styled raster tile through Forge."""


class DeferredMapRefreshWorker:
    """Process bounded durable refresh batches during the configured local window."""

    def __init__(
        self,
        store: MapRefreshStore,
        client: DeferredMapTileClient,
        *,
        clock: Clock = _utc_now,
        local_timezone: str = "America/New_York",
        start_hour: int = 22,
        batch_size: int = 8,
        check_interval_s: float = 300.0,
        request_interval_s: float = 0.25,
        sleeper: Callable[[float], None] = sleep,
    ) -> None:
        if not 0 <= start_hour <= 23:
            raise ValueError("Map refresh start hour must be between 0 and 23.")
        if batch_size < 1:
            raise ValueError("Map refresh batch size must be positive.")
        if check_interval_s <= 0 or request_interval_s < 0:
            raise ValueError("Map refresh intervals are invalid.")
        self._store = store
        self._client = client
        self._clock = clock
        self._timezone = ZoneInfo(local_timezone)
        self._start_hour = start_hour
        self._batch_size = batch_size
        self._check_interval_s = check_interval_s
        self._request_interval_s = request_interval_s
        self._sleeper = sleeper
        self._stop = Event()
        self._thread: Thread | None = None
        self._run_lock = Lock()

    @property
    def is_running(self) -> bool:
        return self._thread is not None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = Thread(
            target=self._loop,
            name="rolling-thunder-map-refresh",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        thread = self._thread
        self._thread = None
        self._stop.set()
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)

    def run_once(self) -> int:
        """Process at most one bounded batch; useful for deterministic tests."""
        if not self._run_lock.acquire(blocking=False):
            return 0
        try:
            now = _aware_utc(self._clock(), "Map refresh worker clock")
            local_now = now.astimezone(self._timezone)
            if local_now.hour < self._start_hour:
                return 0
            internet_available, forge_available = self._client.refresh_health()
            if not internet_available or not forge_available:
                return 0
            try:
                batch = self._store.pending(limit=self._batch_size, now=now)
            except MapRefreshStorageError:
                return 0
            completed = 0
            for index, item in enumerate(batch):
                if index and self._request_interval_s:
                    self._sleeper(self._request_interval_s)
                try:
                    png = self._client.fetch_for_style(item.key.tile, item.key.style)
                    self._store.complete(item, png, refreshed_at=_aware_utc(self._clock(), "Map refresh worker clock"))
                except (OSError, RuntimeError, ValueError, MapRefreshStorageError):
                    try:
                        self._store.fail(item, failed_at=_aware_utc(self._clock(), "Map refresh worker clock"))
                    except MapRefreshStorageError:
                        pass
                    continue
                completed += 1
            return completed
        finally:
            self._run_lock.release()

    def _loop(self) -> None:
        while not self._stop.wait(self._check_interval_s):
            self.run_once()


def _identity_values(key: MapRefreshKey) -> tuple[object, ...]:
    return (
        key.package_id,
        key.style,
        key.tile.zoom,
        key.tile.x,
        key.tile.y,
    )


def _aware_utc(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware.")
    return value.astimezone(UTC)


def _timestamp_text(value: datetime) -> str:
    return _aware_utc(value, "Map refresh timestamp").isoformat()


def _parse_timestamp(raw: str) -> datetime:
    value = datetime.fromisoformat(raw)
    return _aware_utc(value, "Stored map refresh timestamp")
