"""Local-first asynchronous CQ ranking adapter; no radio or provider authority."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from rolling_thunder.ft8.domain import FT8CQActivity
from rolling_thunder.ft8.dx_ranking import CQCandidate, RankedCQ, score_cq
from rolling_thunder.ft8.ranking_cache import FT8RankingCache


class FT8BrowserRanking:
    """Rank visible stations using a bounded local worker, never wait in UI."""

    def __init__(self, *, max_workers: int = 2) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ft8-rank")
        self._cache = FT8RankingCache(self._executor)
        self._pending: frozenset[str] = frozenset()

    @property
    def pending_callsigns(self) -> frozenset[str]:
        return self._pending

    def order(
        self,
        activity: tuple[FT8CQActivity, ...],
        *,
        local_grid: str | None,
        band: str,
    ) -> tuple[FT8CQActivity, ...]:
        now = datetime.now(UTC)
        rankings = []
        for item in activity:
            candidate = CQCandidate(item.callsign, item.grid, item.snr_db)
            def calculate(candidate: CQCandidate = candidate) -> RankedCQ:
                return score_cq(candidate, local_grid=local_grid, now_utc=now)

            rankings.append(
                self._cache.view(item.callsign, band, local_grid, item.grid, calculate)
            )
        self._pending = frozenset(
            entry.callsign for entry in rankings if entry.ranking is None
        )
        by_callsign = {item.callsign: item for item in activity}
        return tuple(by_callsign[entry.callsign] for entry in self._cache.order(tuple(rankings)))

    def close(self) -> None:
        self._cache.invalidate()
        self._executor.shutdown(wait=False, cancel_futures=True)
