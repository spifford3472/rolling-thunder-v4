"""Typed configuration for the independent Forge callsign-info service."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, ValidationError


class ForgeCallsignInfoConfigurationError(Exception):
    """Raised when callsign-info configuration cannot be loaded safely."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CallsignInfoServerConfig(_Model):
    bind_host: str = "127.0.0.1"
    bind_port: int = Field(default=8788, ge=1, le=65535)


class CallsignInfoWavelogConfig(_Model):
    base_url: AnyHttpUrl = AnyHttpUrl("http://127.0.0.1:8086")
    station_location_name: str = "Mobile"
    request_timeout_s: float = Field(default=5.0, gt=0, le=60)


class CallsignInfoWeatherConfig(_Model):
    enabled: bool = True
    endpoint: AnyHttpUrl = AnyHttpUrl("https://api.open-meteo.com/v1/forecast")
    request_timeout_s: float = Field(default=5.0, gt=0, le=60)
    cache_ttl_s: float = Field(default=900.0, gt=0, le=3600)


class ForgeCallsignInfoConfig(_Model):
    server: CallsignInfoServerConfig = CallsignInfoServerConfig()
    wavelog: CallsignInfoWavelogConfig = CallsignInfoWavelogConfig()
    weather: CallsignInfoWeatherConfig = CallsignInfoWeatherConfig()
    qrz_request_timeout_s: float = Field(default=5.0, gt=0, le=60)
    profile_cache_ttl_s: float = Field(default=5_184_000.0, gt=0, le=31_536_000)
    negative_profile_cache_ttl_s: float = Field(default=86_400.0, gt=0, le=604_800)
    history_cache_ttl_s: float = Field(default=60.0, gt=0, le=600)
    station_cache_ttl_s: float = Field(default=21_600.0, gt=0, le=86_400)


def load_forge_callsign_info_config(path: Path) -> ForgeCallsignInfoConfig:
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ForgeCallsignInfoConfigurationError(
            f"Callsign-info configuration could not be read: {path}: {error}"
        ) from error
    try:
        raw: Any = yaml.safe_load(raw_text)
    except yaml.YAMLError as error:
        raise ForgeCallsignInfoConfigurationError(
            f"Callsign-info configuration contains invalid YAML: {error}"
        ) from error
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ForgeCallsignInfoConfigurationError(
            "Callsign-info configuration root must be a mapping."
        )
    try:
        return ForgeCallsignInfoConfig.model_validate(raw)
    except ValidationError as error:
        details = "; ".join(
            f"{'.'.join(str(p) for p in item['loc'])}: {item['msg']}"
            for item in error.errors(include_url=False)
        )
        raise ForgeCallsignInfoConfigurationError(
            f"Callsign-info configuration validation failed: {details}"
        ) from error
