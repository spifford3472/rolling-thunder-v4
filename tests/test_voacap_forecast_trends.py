from datetime import UTC, datetime, timedelta

from rolling_thunder.voacap_forecast_trends import ForecastPoint, compare_previous_local_day


def point(valid: datetime, *, issued: datetime | None = None, path: str = "EM79-DM75", snr: float = -10.0) -> ForecastPoint:
    return ForecastPoint(
        issued_at_utc=issued or (valid - timedelta(hours=2)),
        valid_at_utc=valid,
        model_version="local-model-1",
        path_identity=path,
        equipment_identity="mobile-ant-20w",
        band="20m",
        reliability=0.6,
        predicted_snr_db=snr,
    )


def test_yesterday_same_local_clock_hour() -> None:
    now = point(datetime(2026, 10, 10, 18, tzinfo=UTC), snr=-6)
    prior = point(datetime(2026, 10, 9, 18, tzinfo=UTC))
    result = compare_previous_local_day(now, [prior])
    assert result.status == "comparable"
    assert result.snr_change_db == 4
    assert result.reliability_change == 0


def test_unmatched_paths_not_misrepresented() -> None:
    now = point(datetime(2026, 10, 10, 18, tzinfo=UTC))
    yesterday = point(datetime(2026, 10, 9, 18, tzinfo=UTC), path="other")
    assert compare_previous_local_day(now, [yesterday]).status == "no_comparable_yesterday"


def test_hindcast_is_excluded() -> None:
    now = point(datetime(2026, 10, 10, 18, tzinfo=UTC), issued=datetime(2026, 10, 11, tzinfo=UTC))
    assert compare_previous_local_day(now, []).status == "not_prior_forecast"


def test_dst_ambiguity_is_reported() -> None:
    now = point(datetime(2026, 11, 2, 6, tzinfo=UTC))
    before = point(datetime(2026, 11, 1, 5, tzinfo=UTC))
    after = point(datetime(2026, 11, 1, 6, tzinfo=UTC))
    assert compare_previous_local_day(now, [before, after]).status == "ambiguous_dst_or_multiple_forecasts"
