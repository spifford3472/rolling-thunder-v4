"""Composition helpers for the Pi-side Forge client stack."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from time import monotonic

from rolling_thunder.config import ForgeConfig
from rolling_thunder.forge_client import HttpForgeSpotClient
from rolling_thunder.forge_location_client import HttpForgeLocationClient
from rolling_thunder.forge_spot_cache_repository import ForgeSpotCacheRepository
from rolling_thunder.forge_weather_cache_repository import ForgeWeatherCacheRepository
from rolling_thunder.forge_weather_client import HttpForgeWeatherClient
from rolling_thunder.gps import GPSState
from rolling_thunder.http_home_platform import HttpTransport
from rolling_thunder.pi_forge_location_publisher import (
    PiForgeLocationPublisher,
    PiForgeLocationPublishingService,
)
from rolling_thunder.pi_forge_spot_polling import ExecutorFactory, PiForgeSpotPollingService
from rolling_thunder.pi_forge_spot_service import PiForgeSpotService
from rolling_thunder.pi_forge_weather_polling import (
    PiForgeWeatherPollingService,
    WeatherExecutorFactory,
)
from rolling_thunder.pi_forge_weather_service import PiForgeWeatherService
from rolling_thunder.radio_polling import PollScheduler
from rolling_thunder.threading_scheduler import ThreadingPollScheduler

GPSStateSource = Callable[[], GPSState]
Clock = Callable[[], datetime]
MonotonicClock = Callable[[], float]


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


def build_pi_forge_weather_polling(
    config: ForgeConfig,
    *,
    database_path: Path,
    scheduler: PollScheduler | None = None,
    transport: HttpTransport | None = None,
    executor_factory: WeatherExecutorFactory | None = None,
) -> PiForgeWeatherPollingService | None:
    """Build the optional retained Forge weather polling stack for the Pi."""
    weather_config = config.weather
    if not weather_config.enabled:
        return None

    api_url = config.api_url
    if not config.enabled or api_url is None:
        raise ValueError("Forge must be enabled with an API URL for retained weather.")

    client = HttpForgeWeatherClient(
        str(api_url),
        timeout_s=config.request_timeout_s,
        max_response_bytes=config.max_response_bytes,
        transport=transport,
    )
    cache = ForgeWeatherCacheRepository(database_path)
    service = PiForgeWeatherService(
        client,
        cache,
        stale_after_s=weather_config.stale_after_s,
    )
    return PiForgeWeatherPollingService(
        service,
        scheduler or ThreadingPollScheduler(),
        interval_s=weather_config.refresh_interval_s,
        refresh_on_start=weather_config.refresh_on_start,
        executor_factory=executor_factory,
    )


def build_pi_forge_location_publishing(
    config: ForgeConfig,
    state_source: GPSStateSource,
    *,
    scheduler: PollScheduler | None = None,
    transport: HttpTransport | None = None,
    executor_factory: ExecutorFactory | None = None,
    clock: Clock | None = None,
    monotonic_clock: MonotonicClock = monotonic,
    publish_interval_s: float = 600.0,
    retry_interval_s: float = 60.0,
    unusable_retry_interval_s: float = 30.0,
    scheduler_interval_s: float = 30.0,
    maximum_gps_sample_age_s: float = 5.0,
) -> PiForgeLocationPublishingService | None:
    """Build the optional background Pi-to-Forge GPS location publisher."""
    if not config.enabled:
        return None

    api_url = config.api_url
    if api_url is None:
        raise ValueError("Forge API URL is required when location publishing is enabled.")

    client = HttpForgeLocationClient(
        str(api_url),
        timeout_s=config.request_timeout_s,
        transport=transport,
    )
    publisher = PiForgeLocationPublisher(
        state_source,
        client,
        clock=clock,
        monotonic_clock=monotonic_clock,
        maximum_gps_sample_age_s=maximum_gps_sample_age_s,
    )
    return PiForgeLocationPublishingService(
        publisher,
        scheduler or ThreadingPollScheduler(),
        scheduler_interval_s=scheduler_interval_s,
        publish_interval_s=publish_interval_s,
        retry_interval_s=retry_interval_s,
        unusable_retry_interval_s=unusable_retry_interval_s,
        monotonic_clock=monotonic_clock,
        executor_factory=executor_factory,
    )
