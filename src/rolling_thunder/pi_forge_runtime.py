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
from rolling_thunder.forge_weather_alert_cache_repository import (
    ForgeWeatherAlertCacheRepository,
)
from rolling_thunder.forge_weather_alert_client import (
    HttpForgeWeatherAlertClient,
)
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
from rolling_thunder.pi_forge_weather_alert_polling import (
    PiForgeWeatherAlertPollingService,
    WeatherAlertExecutorFactory,
)
from rolling_thunder.pi_forge_weather_alert_service import (
    PiForgeWeatherAlertService,
)
from rolling_thunder.pi_forge_weather_polling import (
    PiForgeWeatherPollingService,
    WeatherExecutorFactory,
)
from rolling_thunder.pi_forge_weather_service import PiForgeWeatherService
from rolling_thunder.pi_weather_alert_location_guard import (
    PiWeatherAlertLocationGuard,
)
from rolling_thunder.radio_polling import PollScheduler
from rolling_thunder.threading_scheduler import ThreadingPollScheduler
from rolling_thunder.weather_alert_audio import (
    AplayWeatherAlertAudioPlayer,
    WeatherAlertAudioPlayer,
)
from rolling_thunder.weather_alert_notification_policy import (
    WeatherAlertNotificationController,
)
from rolling_thunder.weather_alert_notification_repository import (
    WeatherAlertNotificationRepository,
)

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


def build_pi_forge_weather_alert_polling(
    config: ForgeConfig,
    state_source: GPSStateSource,
    *,
    database_path: Path,
    scheduler: PollScheduler | None = None,
    transport: HttpTransport | None = None,
    executor_factory: WeatherAlertExecutorFactory | None = None,
    audio_player: WeatherAlertAudioPlayer | None = None,
    clock: Clock | None = None,
    monotonic_clock: MonotonicClock = monotonic,
) -> PiForgeWeatherAlertPollingService | None:
    """Build location-aware retained Forge alert polling for the Pi."""
    alert_config = config.weather_alerts

    if not alert_config.enabled:
        return None

    api_url = config.api_url

    if not config.enabled or api_url is None:
        raise ValueError(
            "Forge must be enabled with an API URL "
            "for retained weather alerts."
        )

    client = HttpForgeWeatherAlertClient(
        str(api_url),
        timeout_s=config.request_timeout_s,
        max_response_bytes=config.max_response_bytes,
        transport=transport,
        clock=clock,
    )

    cache = ForgeWeatherAlertCacheRepository(
        database_path
    )

    service = PiForgeWeatherAlertService(
        client,
        cache,
        now=clock,
    )

    location_guard = PiWeatherAlertLocationGuard(
        state_source,
        monotonic_clock=monotonic_clock,
        location_publish_interval_s=(
            alert_config.location_publish_interval_s
        ),
    )

    notifications = WeatherAlertNotificationController(
        WeatherAlertNotificationRepository(
            database_path
        ),
        now=clock,
    )

    effective_audio_player = audio_player

    if effective_audio_player is None:
        effective_audio_player = AplayWeatherAlertAudioPlayer(
            audio_device=alert_config.audio_device,
        )

    return PiForgeWeatherAlertPollingService(
        service,
        location_guard,
        notifications,
        scheduler or ThreadingPollScheduler(),
        interval_s=alert_config.refresh_interval_s,
        refresh_on_start=alert_config.refresh_on_start,
        executor_factory=executor_factory,
        audio_player=effective_audio_player,
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

    if config.weather_alerts.enabled:
        alert_location_interval_s = (
            config.weather_alerts.location_publish_interval_s
        )

        # Location-aware alerts must never inherit the ordinary ten-minute
        # retained-location cadence. Caller-supplied values may make these
        # intervals faster, but never slower than the alert safety bounds.
        publish_interval_s = min(
            publish_interval_s,
            alert_location_interval_s,
        )
        retry_interval_s = min(
            retry_interval_s,
            alert_location_interval_s,
        )
        unusable_retry_interval_s = min(
            unusable_retry_interval_s,
            5.0,
        )
        scheduler_interval_s = min(
            scheduler_interval_s,
            5.0,
        )

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
