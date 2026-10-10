from concurrent.futures import Future

from rolling_thunder.ft8.dx_ranking import RankedCQ
from rolling_thunder.ft8.ranking_cache import FT8RankingCache


class ExecutorStub:
    def __init__(self):
        self.work = []

    def submit(self, fn):
        future = Future()
        self.work.append((fn, future))
        return future


def test_immediate_new_station_and_background_completion():
    ex = ExecutorStub()
    clock = [0.0]
    cache = FT8RankingCache(ex, clock=lambda: clock[0])
    rank = RankedCQ("DX1", 84, 9000, "medium", "test")
    kwargs = ("DX1", "20m", "EM79", "JN58", lambda: rank)
    first = cache.view(*kwargs)
    assert first.pending and first.ranking is None
    assert len(ex.work) == 1
    assert cache.view(*kwargs).pending and len(ex.work) == 1
    ex.work[0][1].set_result(ex.work[0][0]())
    complete = cache.view(*kwargs)
    assert complete.ranking == rank and not complete.pending
    clock[0] = 1799
    assert cache.view(*kwargs).ranking == rank and len(ex.work) == 1
    clock[0] = 1800
    refreshed = cache.view(*kwargs)
    assert refreshed.stale and refreshed.pending and refreshed.ranking == rank
    assert len(ex.work) == 2


def test_pending_at_top_and_stable_order():
    rank = RankedCQ("A", 99, 1000, "medium", "test")
    ex = ExecutorStub()
    cache = FT8RankingCache(ex)
    items = (
        cache.view("A", "20m", "EM79", "FN20", lambda: rank),
        cache.view("B", "20m", "EM79", "JN58", lambda: rank),
    )
    assert [x.callsign for x in cache.order(items)] == ["A", "B"]
    ex.work[0][1].set_result(rank)
    a = cache.view("A", "20m", "EM79", "FN20", lambda: rank)
    b = cache.view("B", "20m", "EM79", "JN58", lambda: rank)
    assert [x.callsign for x in cache.order((a, b))] == ["B", "A"]


def test_context_separation_failure_and_invalidation():
    ex = ExecutorStub()
    cache = FT8RankingCache(ex)
    f = lambda: RankedCQ("DX", 10, None, "low", "test")
    cache.view("DX", "20m", "EM79", "FN20", f)
    cache.view("DX", "40m", "EM79", "FN20", f)
    assert len(ex.work) == 2
    ex.work[0][1].set_exception(ConnectionError("Forge unavailable"))
    assert cache.view("DX", "20m", "EM79", "FN20", f).ranking is None
    cache.invalidate()
    assert cache.view("DX", "20m", "EM79", "FN20", f).ranking is None


def test_late_old_result_after_invalidate_not_applied():
    ex = ExecutorStub()
    cache = FT8RankingCache(ex)
    f = lambda: RankedCQ("DX", 10, None, "low", "test")
    cache.view("DX", "20m", "EM79", "FN20", f)
    cache.invalidate()
    cache.view("DX", "20m", "EM79", "FN20", f)
    assert len(ex.work) == 2
    assert cache.view("DX", "20m", "EM79", "FN20", f).ranking is None
