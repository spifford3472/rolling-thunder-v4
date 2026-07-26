"""Composition helpers and typed settings for configured POTA spot services."""

from datetime import UTC, datetime

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field

from rolling_thunder.http_home_platform import HttpTransport
from rolling_thunder.http_pota_spot_source import HttpPotaSpotSource
from rolling_thunder.pota_spot_polling import PotaSpotPollingService
from rolling_thunder.pota_spot_service import PotaSpotService
from rolling_thunder.pota_spot_source import (
    MockPotaSpotSource,
    PotaSpotFetchResult,
    PotaSpotSource,
    PotaSpotSourceAvailability,
)
from rolling_thunder.radio_polling import PollScheduler


class PotaSpotsRuntimeConfig(BaseModel):
    """Immutable runtime settings for optional POTA spot retrieval."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = False
    base_url: AnyHttpUrl = AnyHttpUrl("https://api.pota.app")
    request_timeout_s: float = Field(default=5.0, gt=0, le=60)
    refresh_interval_s: float = Field(default=60.0, gt=0, le=3_600)
    refresh_on_start: bool = True


def build_pota_spot_polling(
    config: PotaSpotsRuntimeConfig,
    scheduler: PollScheduler,
    *,
    mock_mode: bool,
    transport: HttpTransport | None = None,
) -> PotaSpotPollingService | None:
    """Build configured POTA spot services without starting background work."""
    if not config.enabled:
        return None

    source: PotaSpotSource
    if mock_mode:
        source = MockPotaSpotSource(
            PotaSpotFetchResult(
                availability=PotaSpotSourceAvailability.AVAILABLE,
                fetched_at=datetime.now(UTC),
            )
        )
    else:
        source = HttpPotaSpotSource(
            str(config.base_url),
            timeout_s=config.request_timeout_s,
            transport=transport,
        )

    return PotaSpotPollingService(
        PotaSpotService(source),
        scheduler,
        interval_s=config.refresh_interval_s,
        refresh_on_start=config.refresh_on_start,
    )
