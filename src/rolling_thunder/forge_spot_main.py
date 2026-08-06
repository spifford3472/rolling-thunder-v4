"""Independent console process for Forge spot aggregation and read-only REST."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from threading import Thread
from typing import Protocol

from rolling_thunder.forge_config import (
    ForgeApplicationConfig,
    ForgeConfigurationError,
    ForgeLogLevel,
    load_forge_config,
)
from rolling_thunder.forge_pota_provider import ForgePotaSpotProvider
from rolling_thunder.forge_snapshot_repository import (
    ForgeSnapshotStorageError,
    SqliteForgeSnapshotRepository,
)
from rolling_thunder.forge_spot_aggregation import ForgeSpotAggregationService
from rolling_thunder.forge_spot_api import (
    ForgeHttpServer,
    ForgeSpotApiApplication,
)
from rolling_thunder.forge_spot_polling import ForgeSpotPollingService
from rolling_thunder.http_home_platform import HttpTransport
from rolling_thunder.http_pota_spot_source import HttpPotaSpotSource
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
    """Own the independent Forge polling and HTTP server lifecycles."""

    def __init__(
        self,
        polling: ForgeSpotPollingService,
        server: ForgeServer,
        *,
        logger: logging.Logger,
    ) -> None:
        self.polling = polling
        self.server = server
        self._logger = logger

    def run(self) -> None:
        """Serve retained state immediately, then start provider refreshes."""
        host, port = self.server.server_address
        server_thread = Thread(
            target=self.server.serve_forever,
            name="rolling-thunder-forge-spot-http",
            daemon=True,
        )
        server_thread.start()
        self._logger.info("Forge spot API listening on http://%s:%s", host, port)

        try:
            self.polling.start()
            server_thread.join()
        finally:
            self.server.shutdown()
            self.polling.stop()
            self.server.close()
            server_thread.join(timeout=5.0)


def build_parser() -> argparse.ArgumentParser:
    """Build the independent Forge spot-service argument parser."""
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
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    logger.addHandler(handler)
    return logger


def build_forge_runtime(
    config: ForgeApplicationConfig,
    *,
    scheduler: PollScheduler | None = None,
    server_factory: ForgeServerFactory | None = None,
    transport: HttpTransport | None = None,
    logger: logging.Logger | None = None,
) -> ForgeSpotRuntime:
    """Compose Forge providers, durability, polling, and read-only HTTP."""
    process_logger = logger or logging.getLogger(_LOGGER_NAME)
    if not config.pota.enabled:
        raise ForgeRuntimeConfigurationError(
            "No Forge spot provider is enabled; enable the POTA provider."
        )

    repository = SqliteForgeSnapshotRepository(config.storage.database_path)
    source = HttpPotaSpotSource(
        str(config.pota.base_url).rstrip("/"),
        timeout_s=config.pota.request_timeout_s,
        transport=transport,
    )
    provider = ForgePotaSpotProvider(source)
    aggregation = ForgeSpotAggregationService((provider,), repository)
    polling_scheduler = scheduler or ThreadedPollScheduler()
    polling = ForgeSpotPollingService(
        aggregation,
        polling_scheduler,
        interval_s=config.aggregation.refresh_interval_s,
        refresh_on_start=config.aggregation.refresh_on_start,
    )
    application = ForgeSpotApiApplication(aggregation)
    factory = server_factory or _default_server_factory
    server = factory(
        config.server.bind_host,
        config.server.bind_port,
        application,
    )
    return ForgeSpotRuntime(polling, server, logger=process_logger)


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
    except ForgeConfigurationError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return EXIT_CONFIGURATION_ERROR

    logger = configure_forge_logging(config.logging_level)
    try:
        runtime = build_forge_runtime(config, logger=logger)
    except (ForgeRuntimeConfigurationError, ForgeSnapshotStorageError, OSError) as error:
        logger.error("Forge spot service could not start: %s", error)
        return EXIT_RUNTIME_ERROR

    try:
        runtime.run()
    except KeyboardInterrupt:
        logger.info("Forge spot service interrupted; shutting down.")
    except OSError as error:
        logger.error("Forge spot service failed: %s", error)
        return EXIT_RUNTIME_ERROR
    return EXIT_SUCCESS


if __name__ == "__main__":
    raise SystemExit(main())
