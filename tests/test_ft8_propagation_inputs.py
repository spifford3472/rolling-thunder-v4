from datetime import UTC, datetime, timedelta

import pytest

from rolling_thunder.ft8.propagation_inputs import (
    ForecastSource,
    ForecastState,
    FuturePropagationInputs,
    PropagationForecast,
)

NOW = datetime(2026, 10, 10, 21, tzinfo=UTC)


def test_missing_sources_are_inert_and_unusable():
    inputs = FuturePropagationInputs()
    assert not inputs.voacap.usable_at(NOW)
    assert not inputs.space_weather.usable_at(NOW)


def test_available_forecast_requires_validity_and_expires():
    with pytest.raises(ValueError):
        PropagationForecast(ForecastSource.VOACAP, ForecastState.AVAILABLE)
    snapshot = PropagationForecast(
        ForecastSource.VOACAP, ForecastState.AVAILABLE, NOW, NOW + timedelta(hours=1)
    )
    assert snapshot.usable_at(NOW)
    assert not snapshot.usable_at(NOW + timedelta(hours=2))
    assert not snapshot.usable_at(NOW - timedelta(seconds=1))


def test_wrong_source_and_naive_timestamp_rejected():
    with pytest.raises(ValueError):
        FuturePropagationInputs(voacap=PropagationForecast(ForecastSource.SPACE_WEATHER))
    with pytest.raises(ValueError):
        PropagationForecast(ForecastSource.VOACAP, observed_at_utc=NOW.replace(tzinfo=None))
    with pytest.raises(ValueError):
        PropagationForecast(ForecastSource.VOACAP, ForecastState.AVAILABLE, NOW, NOW - timedelta(seconds=1))
