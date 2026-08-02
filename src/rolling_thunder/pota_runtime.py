"""Composition helper for configured POTA spot services."""

from pathlib import Path

from rolling_thunder.config import PotaSpotsConfig
from rolling_thunder.http_home_platform import HttpTransport
from rolling_thunder.http_pota_spot_source import HttpPotaSpotSource
from rolling_thunder.pota_spot_cache_repository import (
    PotaSpotCacheRepository,
)
from rolling_thunder.pota_spot_polling import PotaSpotPollingService
from rolling_thunder.pota_spot_service import PotaSpotService
from rolling_thunder.radio_polling import PollScheduler


def build_pota_spot_polling(
    config: PotaSpotsConfig,
    scheduler: PollScheduler,
    *,
    database_path: Path,
    mock_mode: bool,
    transport: HttpTransport | None = None,
) -> PotaSpotPollingService | None:
    """Build configured POTA spot services without starting background work."""
    if not config.enabled:
        return None

    # Hardware mock mode controls local radio and GPS adapters only. POTA is a
    # network information service and must continue using its configured HTTP
    # source so a mock radio can still display live activator spots.
    _ = mock_mode
    source = HttpPotaSpotSource(
        str(config.base_url),
        timeout_s=config.request_timeout_s,
        transport=transport,
    )

    return PotaSpotPollingService(
        PotaSpotService(
            source,
            cache=PotaSpotCacheRepository(database_path),
        ),
        scheduler,
        interval_s=config.refresh_interval_s,
        refresh_on_start=config.refresh_on_start,
    )
