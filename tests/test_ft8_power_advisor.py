"""Guardrails for the recommendation-only FT8 empirical power policy."""
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from rolling_thunder.ft8.power_advisor import (
    FT8PowerObservation,
    FT8PowerPolicy,
    recommend_power,
)


def test_configured_auto_ceilings_and_unknown_band_fail_closed() -> None:
    policy = FT8PowerPolicy()
    assert policy.clamp("10m", 70) == 30
    assert policy.clamp("12m", 70) == 40
    assert policy.clamp("15m", 70) == 40
    assert policy.clamp(None, 70) == 30
    assert policy.clamp("20m", 70) == 70
    with pytest.raises(ValidationError):
        FT8PowerPolicy(max_auto_watts_by_band={"10m": 101})


def test_starts_at_20_and_does_not_actuate() -> None:
    policy = FT8PowerPolicy(adaptive_enabled=True)
    at = datetime(2026, 10, 10, 12, tzinfo=UTC)
    advice = recommend_power(policy,band="10m",at_utc=at)
    assert advice.watts == 20 and advice.advisory_only
    assert "Insufficient" in advice.explanation


def test_same_day_independent_receivers_and_power_required() -> None:
    policy = FT8PowerPolicy(adaptive_enabled=True)
    at = datetime(2026, 10, 10, 12, tzinfo=UTC)
    observations = tuple(
        FT8PowerObservation(at-timedelta(minutes=i), "10m", f"K{i}ABC", 10, 20)
        for i in range(3)
    )
    advice = recommend_power(policy,band="10m",at_utc=at,reports=observations)
    assert advice.watts == 15 and advice.evidence_receivers == 3
    stale = observations + (FT8PowerObservation(at-timedelta(days=1),"10m","K9ABC",30,20),)
    assert recommend_power(policy,band="10m",at_utc=at,reports=stale).evidence_receivers == 3
    assert recommend_power(policy,band="10m",at_utc=at,reports=observations,
                           manual_override_active=True).watts == 20


def test_weak_or_wrong_power_never_triggers_unfounded_increase() -> None:
    policy = FT8PowerPolicy(adaptive_enabled=True)
    at = datetime(2026, 10, 10, 12, tzinfo=UTC)
    observations = tuple(
        FT8PowerObservation(at, "12m", f"K{i}ABC", -20, 20)
        for i in range(3)
    ) + (FT8PowerObservation(at, "12m", "K4ABC", 15, 40),)
    advice = recommend_power(policy,band="12m",at_utc=at,reports=observations)
    assert advice.watts == 20 and advice.evidence_receivers == 3


def test_config_model_round_trip_and_custom_limit() -> None:
    from rolling_thunder.config import FT8Config

    config = FT8Config.model_validate({
        'power': {'initial_power_watts':20, 'adaptive_enabled': False,
                  'max_auto_watts_by_band': {'10m':25,'12m':35,'15m':40}}
    })
    assert config.power.clamp('10m',70)==25
    assert config.power.clamp('12m',70)==35


def test_fixed_band_safety_ceilings_survive_missing_or_relaxed_config() -> None:
    policy = FT8PowerPolicy(max_auto_watts_by_band={}, default_max_auto_watts=100)
    assert [policy.limit_for(band) for band in ("10m", "12m", "15m")] == [30, 40, 40]
    assert policy.limit_for(None) == 30
    relaxed = FT8PowerPolicy(max_auto_watts_by_band={"10m": 90, "12m": 100, "15m": 70})
    assert [relaxed.limit_for(band) for band in ("10m", "12m", "15m")] == [30, 40, 40]
    stricter = FT8PowerPolicy(max_auto_watts_by_band={"10m": 25})
    assert stricter.limit_for("10m") == 25
