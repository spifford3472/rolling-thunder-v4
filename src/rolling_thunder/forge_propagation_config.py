"""Typed configuration for the standalone Forge propagation-history component."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import AnyHttpUrl, Field, ValidationError

from rolling_thunder.config import ConfigurationModel
from rolling_thunder.forge_pskreporter import PskReporterConfig


class ForgePropagationHistoryConfig(ConfigurationModel):
    enabled: bool = False
    database_path: Path = Path("data/forge-propagation-history.db")
    collection_interval_s: int = Field(default=3600, ge=3600)
    provider_timeout_s: float = Field(default=10.0, gt=0, le=60)
    voacap_enabled: bool = False
    voacap_base_url: AnyHttpUrl = AnyHttpUrl("http://127.0.0.1:8787")
    weather_enrichment_enabled: bool = False
    pskreporter: PskReporterConfig = PskReporterConfig()


class ForgePropagationConfigurationError(ValueError):
    pass


def load_forge_propagation_config(path: Path) -> ForgePropagationHistoryConfig:
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise ForgePropagationConfigurationError(f"cannot read propagation config: {path}") from error
    try:
        config = ForgePropagationHistoryConfig.model_validate(raw)
    except ValidationError as error:
        raise ForgePropagationConfigurationError("invalid propagation configuration") from error
    database_path = config.database_path
    if not database_path.is_absolute():
        database_path = (path.parent / database_path).resolve()
    return config.model_copy(update={"database_path": database_path})
