"""Provider-neutral observable health for persistent Forge DX connections."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import Field, field_validator

from rolling_thunder.domain import DomainModel


class ForgeDxConnectionStatus(DomainModel):
    """Read-only lifecycle snapshot for the configured persistent DX source."""

    source: Literal["dxsummit", "dxspider"]
    state: str = Field(min_length=1, max_length=40)
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65_535)
    channel: str | None = Field(default=None, max_length=100)
    nickname: str | None = Field(default=None, max_length=40)
    connected_since: datetime | None = None
    last_message_at: datetime | None = None
    last_spot_at: datetime | None = None
    reconnect_count: int = Field(ge=0)
    cache_size: int = Field(ge=0)
    last_error: str | None = Field(default=None, max_length=500)

    @field_validator("connected_since", "last_message_at", "last_spot_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("DX connection timestamps must be timezone-aware")
        return value.astimezone(UTC)
