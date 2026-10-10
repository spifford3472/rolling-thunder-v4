"""Nonblocking FT8 ranking cache; caller owns the worker executor lifecycle.

A cache miss never hides a decoded CQ. Worker completion is polled, not awaited.
No provider, radio, or UI imports and no autonomous contact actions.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import Executor, Future
from dataclasses import dataclass
from time import monotonic

from rolling_thunder.ft8.dx_ranking import RankedCQ

_LOG = logging.getLogger(__name__)
TTL_SECONDS = 1800.0


@dataclass(frozen=True)
class DisplayRanking:
    callsign: str
    ranking: RankedCQ | None
    pending: bool
    stale: bool


@dataclass
class _Entry:
    ranking: RankedCQ
    computed_at: float


class FT8RankingCache:
    """Fixed 30-minute TTL with background refresh and stale-while-revalidate.

    Key includes station callsign, band, and the local/remote path grids;
    rankings never cross bands/paths. The caller may invalidate explicitly on
    context/model changes. Each newly decoded CQ is visible immediately.
    """

    def __init__(
        self,
        executor: Executor,
        *,
        clock: Callable[[], float] = monotonic,
        ttl_seconds: float = TTL_SECONDS,
        capacity: int = 1024,
    ) -> None:
        if ttl_seconds <= 0 or capacity < 1:
            raise ValueError("invalid TTL or capacity")
        self._executor = executor
        self._clock = clock
        self._ttl = ttl_seconds
        self._capacity = capacity
        self._entries: dict[tuple[str, str, str, str], _Entry] = {}
        self._pending: dict[tuple[str, str, str, str], Future[RankedCQ]] = {}

    def invalidate(self) -> None:
        """Clear cached data; in-flight results will be ignored."""
        for future in self._pending.values():
            future.cancel()
        self._entries.clear()
        self._pending.clear()

    def view(
        self,
        callsign: str,
        band: str,
        local_grid: str | None,
        remote_grid: str | None,
        compute: Callable[[], RankedCQ],
    ) -> DisplayRanking:
        """Never blocks on a worker or network. A miss is shown as NEW/pending."""
        key = (
            callsign.strip().upper(),
            band.strip().lower(),
            (local_grid or "").upper(),
            (remote_grid or "").upper(),
        )
        now = self._clock()
        future = self._pending.get(key)
        if future is not None and future.done():
            del self._pending[key]
            try:
                ranking = future.result()
            except Exception:  # noqa: BLE001 - provider/worker failures must never hide stations
                _LOG.warning("FT8 ranking worker unavailable for %s", key, exc_info=True)
            else:
                if ranking.callsign.strip().upper() == key[0]:
                    self._entries[key] = _Entry(ranking, now)
                    if len(self._entries) > self._capacity:
                        oldest = min(self._entries, key=lambda item: self._entries[item].computed_at)
                        del self._entries[oldest]
        entry = self._entries.get(key)
        stale = entry is not None and now - entry.computed_at >= self._ttl
        if (entry is None or stale) and key not in self._pending:
            try:
                self._pending[key] = self._executor.submit(compute)
            except RuntimeError:
                pass  # Shutdown/unavailable executor must not hide CQs.
        return DisplayRanking(
            callsign,
            None if entry is None else entry.ranking,
            key in self._pending,
            stale,
        )

    @staticmethod
    def order(items: tuple[DisplayRanking, ...]) -> tuple[DisplayRanking, ...]:
        """New items first; keep insertion order for ties and pending items.

        Caller freezes its cursor/selected station when applying order changes.
        """
        return tuple(sorted(items, key=lambda x: (x.ranking is not None, -(x.ranking.score if x.ranking else 0))))
