"""Provider-neutral weather-radar value objects shared by Forge and Pi."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import Field, field_validator

from rolling_thunder.domain import DomainModel


class RadarProviderStatus(StrEnum):
    """Truthful provider health for optional radar intelligence."""

    STARTING = "starting"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class RadarProductToken(StrEnum):
    """Rolling Thunder-owned radar product identifiers."""

    BASE_REFLECTIVITY = "base_reflectivity"


class RadarSourceMetadata(DomainModel):
    """Provider identity and attribution carried with every radar frame."""

    provider_id: str = Field(min_length=1, max_length=80)
    provider_name: str = Field(min_length=1, max_length=120)
    product: RadarProductToken
    attribution_text: str = Field(min_length=1, max_length=200)
    attribution_url: str = Field(min_length=1, max_length=500)


class RadarFrame(DomainModel):
    """Provider-neutral public metadata for one immutable radar frame."""

    frame_token: str = Field(min_length=16, max_length=128)
    observed_at: datetime
    fetched_at: datetime
    source: RadarSourceMetadata

    @field_validator("observed_at", "fetched_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        """Require provider and fetch timestamps to be timezone-aware UTC values."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("radar frame timestamps must include timezone information")
        return value.astimezone(UTC)
