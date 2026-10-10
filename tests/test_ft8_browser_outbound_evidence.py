from datetime import timedelta
from time import monotonic, sleep

from rolling_thunder.ft8.browser_ranking import FT8BrowserRanking
from rolling_thunder.ft8.domain import FT8CQActivity, FT8Period
from rolling_thunder.ft8.psk_evidence_client import OutboundReceptionObservation


def _cq():
    return FT8CQActivity(
        callsign="DL1ABC", last_period=FT8Period(100), snr_db=-10,
        dt_seconds=0.1, audio_frequency_hz=1200, grid="JN58",
    )


class Reader:
    def __init__(self, *, broken=False):
        self.broken = broken
        self.requests = []

    def lookup(self, *, sender_callsign, target_grid, frequency_hz, now_utc):
        self.requests.append((sender_callsign, target_grid, frequency_hz))
        if self.broken:
            raise OSError("Forge unavailable")
        return OutboundReceptionObservation(now_utc - timedelta(minutes=2), 3, -8)


def _finish(ranking):
    deadline = monotonic() + 2
    while monotonic() < deadline:
        ranking.order((_cq(),), local_grid="EM79", band="20m")
        if not ranking.pending_callsigns:
            return
        sleep(0.005)
    raise AssertionError("worker did not finish")


def test_outbound_lookup_only_from_optional_worker():
    reader = Reader()
    ranking = FT8BrowserRanking(max_workers=1, evidence_reader=reader)
    try:
        assert ranking.order((_cq(),), local_grid="EM79", band="20m")
        _finish(ranking)
        assert reader.requests == [("KI5VNB", "JN58", 14074000)]
    finally:
        ranking.close()


def test_provider_failure_and_unconfigured_are_neutral():
    reader = Reader(broken=True)
    ranking = FT8BrowserRanking(max_workers=1, evidence_reader=reader)
    plain = FT8BrowserRanking(max_workers=1)
    try:
        _finish(ranking)
        _finish(plain)
        failed = ranking._cache._entries
        normal = plain._cache._entries
        assert next(iter(failed.values())).ranking.score == next(iter(normal.values())).ranking.score
    finally:
        ranking.close()
        plain.close()
