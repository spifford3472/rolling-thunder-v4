"""Composition helper for configured POTA spot services."""

from datetime import UTC, datetime

from rolling_thunder.config import PotaSpotsConfig
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


def build_pota_spot_polling(
    config: PotaSpotsConfig,
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
        refresh_immediately=config.refresh_immediately,
    )
