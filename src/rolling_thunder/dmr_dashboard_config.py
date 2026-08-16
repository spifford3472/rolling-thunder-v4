"""Typed deployment configuration for the optional DMR hotspot panel."""

from __future__ import annotations

from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DmrHotspotConfig(BaseModel):
    """Optional local WPSD/MMDVM hotspot monitoring settings."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = False
    host: str | None = None
    ssh_user: str = "pi-star"
    private_key: Path | None = None
    http_timeout_s: float = Field(default=5.0, gt=0, le=60)
    connect_timeout_s: int = Field(default=5, ge=1, le=60)
    history_limit: int = Field(default=20, ge=1, le=100)
    history_refresh_interval_s: float = Field(default=2.0, gt=0, le=60)
    reconnect_delay_s: float = Field(default=2.0, gt=0, le=60)

    @field_validator("host", "ssh_user")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        """Trim optional network/account text and reject blank configured values."""
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized

    @field_validator("private_key", mode="before")
    @classmethod
    def validate_private_key(cls, value: object) -> object:
        """Reject blank/current-directory key paths without requiring the file yet."""
        if value is None:
            return value
        if isinstance(value, str) and not value.strip():
            raise ValueError("must not be blank")
        if isinstance(value, (str, Path)) and str(Path(value)) == ".":
            raise ValueError("must name a private-key file")
        return value

    @model_validator(mode="after")
    def validate_enabled_hotspot(self) -> Self:
        """Require endpoint and restricted SSH key when DMR monitoring is enabled."""
        if not self.enabled:
            return self
        missing: list[str] = []
        if self.host is None:
            missing.append("host")
        if self.private_key is None:
            missing.append("private_key")
        if missing:
            raise ValueError("DMR hotspot monitoring requires " + ", ".join(missing))
        return self
