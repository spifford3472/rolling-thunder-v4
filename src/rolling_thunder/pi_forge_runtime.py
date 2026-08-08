"""Composition helper for the Pi-side Forge shared-spot client stack."""

from __future__ import annotations

from pathlib import Path

from rolling_thunder.config import ForgeConfig
from rolling_thunder.forge_client import HttpForgeSpotClient
from rolling_thunder.forge_spot_cache_repository import ForgeSpotCacheRepository
from rolling_thunder.http_home_platform import HttpTransport
from rolling_thunder.pi_forge_spot_polling import (
    ExecutorFactory,
    PiForgeSpotPollingService,
)
from rolling_thunder.pi_forge_spot_service import PiForgeSpotService
from rolling_thunder.radio_polling import PollScheduler
from rolling_thunder.threading_scheduler import ThreadingPollScheduler


def build_pi_forge_spot_polling(
    config: ForgeConfig,
    *,
    database_path: Path,
    scheduler: PollScheduler | None = None,
    transport: HttpTransport | None = None,
    executor_factory: ExecutorFactory | None = None,
) -> PiForgeSpotPollingService | None:
    """Build the optional Pi Forge spot polling stack from validated config."""
    if not config.enabled:
        return None

    api_url = config.api_url
    if api_url is None:
        raise ValueError("Forge API URL is required when Pi Forge polling is enabled.")

    client = HttpForgeSpotClient(
        str(api_url),
        timeout_s=config.request_timeout_s,
        max_response_bytes=config.max_response_bytes,
        transport=transport,
    )
    cache = ForgeSpotCacheRepository(database_path)
    service = PiForgeSpotService(client, cache)
    return PiForgeSpotPollingService(
        service,
        scheduler or ThreadingPollScheduler(),
        interval_s=config.refresh_interval_s,
        refresh_on_start=config.refresh_on_start,
        executor_factory=executor_factory,
    )
