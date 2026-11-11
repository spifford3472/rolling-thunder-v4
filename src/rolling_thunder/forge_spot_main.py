"""Independent console process for Forge aggregation and private REST."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from threading import Thread
from typing import Protocol

from rolling_thunder.application_secrets import (
    ApplicationSecrets,
    SecretConfigurationError,
    load_application_secrets,
)
from rolling_thunder.forge_config import (
    ForgeApplicationConfig,
    ForgeConfigurationError,
    ForgeLogLevel,
    load_forge_config,
)
from rolling_thunder.forge_dxspider_provider import (
    DxSpiderSessionFactory,
    ForgeDxSpiderSpotProvider,
)
from rolling_thunder.forge_dxsummit_provider import (
    DxSummitIrcSessionFactory,
    ForgeDxSummitSpotProvider,
)
from rolling_thunder.forge_map import ForgeMapRenderer
from rolling_thunder.forge_map_api import MapAwareForgeSpotApiApplication
from rolling_thunder.forge_mobile_location import (
    ForgeMobileLocationService,
    ForgeMobileLocationStorageError,
)
from rolling_thunder.forge_mobile_location_repository import (
    SqliteForgeMobileLocationRepository,
)
from rolling_thunder.forge_noaa_radar import NoaaNwsRadarProvider
from rolling_thunder.forge_nws_weather_alerts import NwsWeatherAlertProvider
from rolling_thunder.forge_ohgo_api import (
    ForgeOhgoBackgroundService,
    OhgoAwareForgeSpotApiApplication,
)
from rolling_thunder.forge_ohgo_credentials import (
    load_ohgo_credential,
    ohgo_enabled_by_operator,
)
from rolling_thunder.forge_ohgo_http import fetch_ohgo_https
from rolling_thunder.forge_ohgo_incidents import ForgeOhgoIncidentProvider
from rolling_thunder.forge_open_meteo_weather import OpenMeteoForgeWeatherProvider
from rolling_thunder.forge_pota_provider import ForgePotaSpotProvider
from rolling_thunder.forge_qrz_enrichment import ForgeQrzEnricher
from rolling_thunder.forge_qrz_provider import ForgeQrzEnrichedSpotProvider
from rolling_thunder.forge_radar import ForgeRadarService
from rolling_thunder.forge_radar_api import RadarAwareForgeSpotApiApplication
from rolling_thunder.forge_radar_polling import (
    ExecutorFactory as RadarExecutorFactory,
)
from rolling_thunder.forge_radar_polling import ForgeRadarPollingService
from rolling_thunder.forge_snapshot_repository import (
    ForgeSnapshotStorageError,
    SqliteForgeSnapshotRepository,
)
from rolling_thunder.forge_spot_aggregation import ForgeSpotAggregationService
from rolling_thunder.forge_spot_api import (
    ForgeHttpServer,
    ForgeSpotApiApplication,
    ForgeWeatherStateSource,
)
from rolling_thunder.forge_spot_polling import ForgeSpotPollingService
from rolling_thunder.forge_spot_provider import ForgeSpotProvider
from rolling_thunder.forge_weather import ForgeWeatherService, ForgeWeatherStorageError
from rolling_thunder.forge_weather_alert_api import (
    WeatherAlertAwareForgeSpotApiApplication,
)
from rolling_thunder.forge_weather_alert_polling import (
    ExecutorFactory as WeatherAlertExecutorFactory,
)
from rolling_thunder.forge_weather_alert_polling import (
    ForgeWeatherAlertPollingService,
)
from rolling_thunder.forge_weather_alert_repository import (
    SqliteForgeWeatherAlertRepository,
)
from rolling_thunder.forge_weather_alerts import (
    ForgeWeatherAlertService,
    ForgeWeatherAlertStorageError,
)
from rolling_thunder.forge_weather_polling import (
    ExecutorFactory as WeatherExecutorFactory,
)
from rolling_thunder.forge_weather_polling import ForgeWeatherPollingService
from rolling_thunder.forge_weather_repository import SqliteForgeWeatherRepository
from rolling_thunder.forge_weather_unavailable import UnavailableForgeWeatherStateSource
from rolling_thunder.http_home_platform import HttpTransport
from rolling_thunder.http_pota_spot_source import HttpPotaSpotSource
from rolling_thunder.qrz_xml import QrzXmlCallsignNameProvider
from rolling_thunder.radio_polling import PollScheduler
from rolling_thunder.threaded_poll_scheduler import ThreadedPollScheduler

DEFAULT_FORGE_CONFIG_PATH = Path("config/forge-spots.yaml")
EXIT_SUCCESS = 0
EXIT_CONFIGURATION_ERROR = 2
EXIT_RUNTIME_ERROR = 3
_LOGGER_NAME = "rolling_thunder.forge_spots"


class ForgeRuntimeConfigurationError(Exception):
    """Raised when enabled Forge process components cannot be composed."""


class ForgeServer(Protocol):
    """Lifecycle boundary implemented by the production HTTP server."""

    @property
    def server_address(self) -> tuple[str, int]:
        """Return the effective bound host and port."""
        ...

    def serve_forever(self) -> None:
        """Serve requests until shutdown."""
        ...

    def shutdown(self) -> None:
        """Stop the serve loop."""
        ...

    def close(self) -> None:
        """Close the listening socket."""
        ...


ForgeServerFactory = Callable[[str, int, ForgeSpotApiApplication], ForgeServer]


class ForgeSpotRuntime:
    """Own Forge spot, location, weather, alerts, radar, and HTTP lifecycles."""

    def __init__(
        self,
        polling: ForgeSpotPollingService,
        server: ForgeServer,
        mobile_location: ForgeMobileLocationService,
        *,
        weather: ForgeWeatherStateSource | None = None,
        weather_polling: ForgeWeatherPollingService | None = None,
        weather_alerts: ForgeWeatherAlertService | None = None,
        weather_alert_polling: ForgeWeatherAlertPollingService | None = None,
        radar: ForgeRadarService | None = None,
        radar_polling: ForgeRadarPollingService | None = None,
        ohgo: ForgeOhgoBackgroundService | None = None,
        dxspider: ForgeDxSpiderSpotProvider | None = None,
        dxsummit: ForgeDxSummitSpotProvider | None = None,
        logger: logging.Logger,
    ) -> None:
        self.polling = polling
        self.server = server
        self.mobile_location = mobile_location
        self.weather = weather
        self.weather_polling = weather_polling
        self.weather_alerts = weather_alerts
        self.weather_alert_polling = weather_alert_polling
        self.radar = radar
        self.radar_polling = radar_polling
        self.ohgo = ohgo
        self.dxspider = dxspider
        self.dxsummit = dxsummit
        self._logger = logger

    def run(self) -> None:
        """Serve retained state immediately, then start background refreshes."""
        host, port = self.server.server_address
        server_thread = Thread(
            target=self.server.serve_forever,
            name="rolling-thunder-forge-spot-http",
            daemon=True,
        )
        server_thread.start()
        self._logger.info("Forge API listening on http://%s:%s", host, port)

        try:
            if self.dxspider is not None:
                self.dxspider.start()
            if self.dxsummit is not None:
                self.dxsummit.start()
            if self.ohgo is not None:
                self.ohgo.start()
            self.polling.start()
            if self.weather_polling is not None:
                self.weather_polling.start()
            if self.weather_alert_polling is not None:
                self.weather_alert_polling.start()
            if self.radar_polling is not None:
                self.radar_polling.start()
            server_thread.join()
        finally:
            self.server.shutdown()
            if self.ohgo is not None:
                self.ohgo.stop()
            if self.radar_polling is not None:
                self.radar_polling.stop()
            if self.weather_alert_polling is not None:
                self.weather_alert_polling.stop()
            if self.weather_polling is not None:
                self.weather_polling.stop()
            self.polling.stop()
            if self.dxsummit is not None:
                self.dxsummit.stop()
            if self.dxspider is not None:
                self.dxspider.stop()
            self.server.close()
            server_thread.join(timeout=5.0)


def build_parser() -> argparse.ArgumentParser:
    """Build the independent Forge service argument parser."""
    parser = argparse.ArgumentParser(
        prog="rolling-thunder-forge-spots",
        description="Forge POTA and DX spot aggregation service",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_FORGE_CONFIG_PATH,
        help=f"Forge YAML configuration path (default: {DEFAULT_FORGE_CONFIG_PATH})",
    )
    return parser


def configure_forge_logging(level: ForgeLogLevel) -> logging.Logger:
    """Configure bounded console logging for the independent process."""
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(level.value)
    logger.propagate = False

    for handler in logger.handlers:
        handler.close()
    logger.handlers.clear()

    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(handler)
    return logger


def validate_forge_secrets(
    config: ForgeApplicationConfig,
    secrets: ApplicationSecrets,
) -> None:
    """Require environment-backed QRZ credentials when enrichment is enabled."""
    if config.qrz.enabled and secrets.qrz is None:
        raise SecretConfigurationError(
            "QRZ enrichment is enabled, but ROLLING_THUNDER_QRZ_USERNAME and "
            "ROLLING_THUNDER_QRZ_PASSWORD are not both configured."
        )


def build_forge_runtime(
    config: ForgeApplicationConfig,
    *,
    scheduler: PollScheduler | None = None,
    weather_scheduler: PollScheduler | None = None,
    weather_alert_scheduler: PollScheduler | None = None,
    radar_scheduler: PollScheduler | None = None,
    server_factory: ForgeServerFactory | None = None,
    transport: HttpTransport | None = None,
    dxspider_session_factory: DxSpiderSessionFactory | None = None,
    dxsummit_session_factory: DxSummitIrcSessionFactory | None = None,
    weather_executor_factory: WeatherExecutorFactory | None = None,
    weather_alert_executor_factory: WeatherAlertExecutorFactory | None = None,
    radar_executor_factory: RadarExecutorFactory | None = None,
    secrets: ApplicationSecrets | None = None,
    logger: logging.Logger | None = None,
) -> ForgeSpotRuntime:
    """Compose spots, retained location/weather/alerts/radar, polling, and REST."""
    process_logger = logger or logging.getLogger(_LOGGER_NAME)
    providers: list[ForgeSpotProvider] = []

    if config.pota.enabled:
        source = HttpPotaSpotSource(
            str(config.pota.base_url).rstrip("/"),
            timeout_s=config.pota.request_timeout_s,
            transport=transport,
        )
        providers.append(ForgePotaSpotProvider(source))

    if config.dxspider.enabled and config.dxsummit.enabled:
        raise ForgeRuntimeConfigurationError("DXSpider and DX Summit cannot both be enabled.")

    dxspider: ForgeDxSpiderSpotProvider | None = None
    if config.dxspider.enabled:
        dxspider = ForgeDxSpiderSpotProvider(
            config.dxspider,
            session_factory=dxspider_session_factory,
        )
        providers.append(dxspider)

    dxsummit: ForgeDxSummitSpotProvider | None = None
    if config.dxsummit.enabled:
        dxsummit = ForgeDxSummitSpotProvider(
            host=config.dxsummit.host,
            port=config.dxsummit.port,
            channel=config.dxsummit.channel,
            nickname=str(config.dxsummit.nickname),
            connect_timeout_s=config.dxsummit.connect_timeout_s,
            read_timeout_s=config.dxsummit.read_timeout_s,
            inactivity_timeout_s=config.dxsummit.inactivity_timeout_s,
            reconnect_initial_s=config.dxsummit.reconnect_initial_s,
            reconnect_max_s=config.dxsummit.reconnect_max_s,
            stable_connection_s=config.dxsummit.stable_connection_s,
            max_spot_age_s=config.dxsummit.max_spot_age_s,
            max_spots=config.dxsummit.max_spots,
            session_factory=dxsummit_session_factory,
        )
        providers.append(dxsummit)

    if not providers:
        raise ForgeRuntimeConfigurationError(
            "No Forge spot provider is enabled; enable POTA, DXSpider, or DX Summit."
        )

    runtime_secrets = secrets or ApplicationSecrets()
    try:
        validate_forge_secrets(config, runtime_secrets)
    except SecretConfigurationError as error:
        raise ForgeRuntimeConfigurationError(str(error)) from error

    if config.qrz.enabled:
        assert runtime_secrets.qrz is not None
        lookup = QrzXmlCallsignNameProvider(
            runtime_secrets.qrz,
            timeout_s=config.qrz.request_timeout_s,
            transport=transport,
        )
        enricher = ForgeQrzEnricher(config.qrz, lookup)
        providers = [ForgeQrzEnrichedSpotProvider(provider, enricher) for provider in providers]

    snapshot_repository = SqliteForgeSnapshotRepository(config.storage.database_path)
    aggregation = ForgeSpotAggregationService(tuple(providers), snapshot_repository)
    mobile_repository = SqliteForgeMobileLocationRepository(config.storage.database_path)
    mobile_location = ForgeMobileLocationService(mobile_repository)

    polling_scheduler = scheduler or ThreadedPollScheduler()
    polling = ForgeSpotPollingService(
        aggregation,
        polling_scheduler,
        interval_s=config.aggregation.refresh_interval_s,
        dx_cache_publish_interval_s=(
            config.aggregation.dx_cache_publish_interval_s
            if dxspider is not None or dxsummit is not None
            else None
        ),
        refresh_on_start=config.aggregation.refresh_on_start,
    )

    weather_state_source: ForgeWeatherStateSource | None = None
    weather_polling: ForgeWeatherPollingService | None = None
    if config.weather.enabled:
        try:
            weather_repository = SqliteForgeWeatherRepository(config.storage.database_path)
        except ForgeWeatherStorageError as error:
            process_logger.error(
                "Forge weather persistence is unavailable; core Forge service will continue: %s",
                error,
            )
            weather_state_source = UnavailableForgeWeatherStateSource(error)
        else:
            weather_provider = OpenMeteoForgeWeatherProvider(
                timeout_s=config.weather.request_timeout_s,
                transport=transport,
                endpoint=str(config.weather.endpoint),
            )
            weather_service = ForgeWeatherService(
                weather_provider,
                weather_repository,
                mobile_location,
                max_forecast_age_s=config.weather.max_forecast_age_s,
                movement_refresh_km=config.weather.movement_refresh_km,
            )
            weather_state_source = weather_service
            weather_polling = ForgeWeatherPollingService(
                weather_service,
                weather_scheduler or ThreadedPollScheduler(),
                check_interval_s=config.weather.check_interval_s,
                refresh_on_start=config.weather.refresh_on_start,
                executor_factory=weather_executor_factory,
            )

    weather_alert_service: ForgeWeatherAlertService | None = None
    weather_alert_polling: ForgeWeatherAlertPollingService | None = None
    if config.weather_alerts.enabled:
        try:
            weather_alert_repository = SqliteForgeWeatherAlertRepository(
                config.storage.database_path
            )
        except ForgeWeatherAlertStorageError as error:
            process_logger.error(
                "Forge weather-alert persistence is unavailable; "
                "core Forge service will continue: %s",
                error,
            )
        else:
            weather_alert_provider = NwsWeatherAlertProvider(
                user_agent=config.weather_alerts.user_agent,
                endpoint=str(config.weather_alerts.endpoint),
                timeout_s=config.weather_alerts.request_timeout_s,
                transport=transport,
            )
            weather_alert_service = ForgeWeatherAlertService(
                weather_alert_provider,
                weather_alert_repository,
                mobile_location,
                location_max_age_s=config.weather_alerts.location_max_age_s,
            )
            weather_alert_polling = ForgeWeatherAlertPollingService(
                weather_alert_service,
                weather_alert_scheduler or ThreadedPollScheduler(),
                check_interval_s=config.weather_alerts.check_interval_s,
                refresh_on_start=config.weather_alerts.refresh_on_start,
                executor_factory=weather_alert_executor_factory,
            )

    radar_service: ForgeRadarService | None = None
    radar_polling: ForgeRadarPollingService | None = None
    if config.radar.enabled:
        radar_provider = NoaaNwsRadarProvider(
            endpoint=str(config.radar.endpoint),
            timeout_s=config.radar.request_timeout_s,
            transport=transport,
        )
        radar_service = ForgeRadarService(
            radar_provider,
            mobile_location,
            stale_after_s=config.radar.stale_after_s,
            hide_after_s=config.radar.hide_after_s,
            maximum_cached_tiles=config.radar.maximum_cached_tiles,
        )
        radar_polling = ForgeRadarPollingService(
            radar_service,
            radar_scheduler or ThreadedPollScheduler(),
            check_interval_s=config.radar.check_interval_s,
            refresh_on_start=config.radar.refresh_on_start,
            executor_factory=radar_executor_factory,
        )

    core_application = ForgeSpotApiApplication(
        aggregation,
        mobile_location=mobile_location,
        weather=weather_state_source,
        dx_connection=dxsummit or dxspider,
    )
    radar_application = RadarAwareForgeSpotApiApplication(
        core_application,
        radar_service,
    )
    map_renderer = (
        ForgeMapRenderer(config.map_tiles, transport=transport)
        if config.map_tiles.enabled
        else None
    )
    map_application = MapAwareForgeSpotApiApplication(
        radar_application,
        map_renderer,
    )
    application: ForgeSpotApiApplication = WeatherAlertAwareForgeSpotApiApplication(
        map_application,
        weather_alert_service,
    )
    # A disabled provider always publishes a truthful unavailable state.
    # The operator must separately configure OHGO credentials on Forge.
    ohgo_enabled = ohgo_enabled_by_operator()
    ohgo_key = load_ohgo_credential() if ohgo_enabled else None
    ohgo_provider = (
        ForgeOhgoIncidentProvider(
            transport=fetch_ohgo_https,
            api_key=ohgo_key,
            enabled=ohgo_enabled,
            region="sw-ohio",
        )
        if ohgo_enabled and ohgo_key
        else None
    )
    ohgo_service = ForgeOhgoBackgroundService(ohgo_provider)
    application = OhgoAwareForgeSpotApiApplication(application, ohgo_service)

    factory = server_factory or _default_server_factory
    server = factory(
        config.server.bind_host,
        config.server.bind_port,
        application,
    )
    return ForgeSpotRuntime(
        polling,
        server,
        mobile_location,
        weather=weather_state_source,
        weather_polling=weather_polling,
        weather_alerts=weather_alert_service,
        weather_alert_polling=weather_alert_polling,
        radar=radar_service,
        radar_polling=radar_polling,
        ohgo=ohgo_service,
        dxspider=dxspider,
        dxsummit=dxsummit,
        logger=process_logger,
    )


def _default_server_factory(
    bind_host: str,
    bind_port: int,
    application: ForgeSpotApiApplication,
) -> ForgeHttpServer:
    return ForgeHttpServer(
        bind_host,
        bind_port,
        application,
        logger=logging.getLogger(_LOGGER_NAME),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Load configuration, compose the service, and run until interrupted."""
    args = build_parser().parse_args(argv)
    try:
        config = load_forge_config(args.config)
        secrets = load_application_secrets()
        validate_forge_secrets(config, secrets)
    except (ForgeConfigurationError, SecretConfigurationError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return EXIT_CONFIGURATION_ERROR

    logger = configure_forge_logging(config.logging_level)
    try:
        runtime = build_forge_runtime(config, secrets=secrets, logger=logger)
    except (
        ForgeRuntimeConfigurationError,
        ForgeSnapshotStorageError,
        ForgeMobileLocationStorageError,
        OSError,
    ) as error:
        logger.error("Forge service could not start: %s", error)
        return EXIT_RUNTIME_ERROR

    try:
        runtime.run()
    except KeyboardInterrupt:
        logger.info("Forge service interrupted; shutting down.")
    except OSError as error:
        logger.error("Forge service failed: %s", error)
        return EXIT_RUNTIME_ERROR
    return EXIT_SUCCESS


if __name__ == "__main__":
    raise SystemExit(main())
