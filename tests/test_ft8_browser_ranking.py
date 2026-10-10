"""Local-only asynchronous ranking contract; no radio/Forge I/O."""
from rolling_thunder.ft8.browser_ranking import FT8BrowserRanking
from rolling_thunder.ft8.domain import FT8CQActivity, FT8Period


def _cq(call: str, grid: str) -> FT8CQActivity:
    return FT8CQActivity(
        callsign=call,
        last_period=FT8Period(100),
        snr_db=-10,
        dt_seconds=0.1,
        audio_frequency_hz=1200,
        grid=grid,
    )


def test_new_cqs_remain_visible_before_and_after_background_scoring():
    ranking = FT8BrowserRanking(max_workers=1)
    try:
        cqs = (_cq("K1ABC", "FN31"), _cq("JA1ABC", "PM95"))
        first = ranking.order(cqs, local_grid="EM79", band="20m")
        assert {row.callsign for row in first} == {"K1ABC", "JA1ABC"}
        # Scoring is never awaited, and both rows remain available.
        second = ranking.order(cqs, local_grid="EM79", band="20m")
        assert {row.callsign for row in second} == {"K1ABC", "JA1ABC"}
    finally:
        ranking.close()
