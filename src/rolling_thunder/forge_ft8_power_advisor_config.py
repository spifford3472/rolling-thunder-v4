"""Validated, atomically reloadable Forge FT8 power-advisor policy.

This configuration describes scientific readiness only.  Even
``armed_when_ready`` cannot command a radio in Phase C5.
"""

from __future__ import annotations

import threading
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, ValidationError, model_validator

from rolling_thunder.config import ConfigurationModel


class PowerAdvisorMode(StrEnum):
    OFF = "off"
    SHADOW = "shadow"
    ARMED_WHEN_READY = "armed_when_ready"


class ForgeFT8PowerAdvisorConfigurationError(ValueError):
    """Raised when the C5 policy cannot be parsed without ambiguity."""


class FT8PowerAdvisorPolicy(ConfigurationModel):
    schema_version: int = Field(default=1, ge=1, le=1)
    mode: PowerAdvisorMode = PowerAdvisorMode.OFF
    minimum_independent_forecast_cells: int = Field(default=20_000, ge=1)
    minimum_real_transmitted_attempts: int = Field(default=2_000, ge=1)
    minimum_attempts_per_operating_segment: int = Field(default=100, ge=1)
    minimum_forward_holdout_days: int = Field(default=30, ge=1)
    minimum_forward_holdout_attempts: int = Field(default=200, ge=1)
    maximum_calibration_error_percentage_points: float = Field(default=10.0, gt=0, le=100)
    require_heldout_noninferiority_vs_20w: bool = True
    require_fresh_prospective_forecast: bool = True
    require_valid_asof_provenance: bool = True
    pinned_model_version: str = Field(min_length=1, max_length=120)
    fallback_start_watts: int = Field(default=20, ge=5, le=100, multiple_of=5)
    qualification_hysteresis_evaluations: int = Field(default=2, ge=1, le=100)
    maximum_forecast_age_seconds: int = Field(default=21_600, ge=1, le=604_800)
    maximum_forge_latency_seconds: float = Field(default=5.0, gt=0, le=300)

    @model_validator(mode="after")
    def fixed_c5_safety_contract(self) -> FT8PowerAdvisorPolicy:
        if self.fallback_start_watts != 20:
            raise ValueError("Phase C5 fallback_start_watts must remain 20")
        return self


def load_ft8_power_advisor_policy(path: Path) -> FT8PowerAdvisorPolicy:
    try:
        raw_text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ForgeFT8PowerAdvisorConfigurationError(
            f"cannot read FT8 power-advisor policy: {path}"
        ) from error
    try:
        raw: Any = yaml.safe_load(raw_text)
    except yaml.YAMLError as error:
        raise ForgeFT8PowerAdvisorConfigurationError("invalid FT8 power-advisor YAML") from error
    if not isinstance(raw, dict):
        raise ForgeFT8PowerAdvisorConfigurationError(
            "FT8 power-advisor policy root must be a mapping"
        )
    try:
        return FT8PowerAdvisorPolicy.model_validate(raw)
    except ValidationError as error:
        details = "; ".join(
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
            for item in error.errors(include_url=False)
        )
        raise ForgeFT8PowerAdvisorConfigurationError(
            f"invalid FT8 power-advisor policy: {details}"
        ) from error


class AtomicPowerAdvisorPolicy:
    """Publish a new immutable policy only after the complete file validates."""

    def __init__(self, initial: FT8PowerAdvisorPolicy) -> None:
        self._lock = threading.Lock()
        self._current = initial

    def snapshot(self) -> FT8PowerAdvisorPolicy:
        with self._lock:
            return self._current

    def reload(self, path: Path) -> FT8PowerAdvisorPolicy:
        candidate = load_ft8_power_advisor_policy(path)
        with self._lock:
            self._current = candidate
            return self._current
