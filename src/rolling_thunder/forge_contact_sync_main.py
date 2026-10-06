"""Independent Forge process that owns Rolling Thunder to Wavelog synchronization."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from rolling_thunder.application_secrets import (
    SecretConfigurationError,
    load_application_secrets,
)
from rolling_thunder.forge_contact_sync import (
    ForgeContactSyncRepository,
    ForgeContactSyncService,
    ForgeContactSyncStorageError,
)
from rolling_thunder.forge_contact_sync_api import (
    ForgeContactHttpServer,
    ForgeContactSyncApiApplication,
)
from rolling_thunder.forge_contact_sync_config import (
    ForgeContactSyncConfigurationError,
    load_forge_contact_sync_config,
)
from rolling_thunder.forge_ft8_performance import (
    ForgeFT8PerformanceRepository,
    ForgeFT8PerformanceService,
    ForgeFT8PerformanceStorageError,
)
from rolling_thunder.wavelog import WavelogClient

DEFAULT_CONFIG_PATH = Path("config/forge-contact-sync.yaml")
EXIT_SUCCESS = 0
EXIT_CONFIGURATION_ERROR = 2
EXIT_RUNTIME_ERROR = 3
_LOGGER_NAME = "rolling_thunder.forge_contact_sync"


def build_parser() -> argparse.ArgumentParser:
    """Build command-line options for the independent service."""
    parser = argparse.ArgumentParser(
        prog="rolling-thunder-forge-contact-sync",
        description="Forge-local Rolling Thunder to Wavelog synchronization service",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"Configuration path (default: {DEFAULT_CONFIG_PATH})",
    )
    return parser


def configure_logging() -> logging.Logger:
    """Configure concise service logging without secret values."""
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in logger.handlers:
        handler.close()
    logger.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(handler)
    return logger


def main(argv: Sequence[str] | None = None) -> int:
    """Load configuration/secrets and serve the private contact-sync API."""
    args = build_parser().parse_args(argv)
    logger = configure_logging()
    try:
        config = load_forge_contact_sync_config(args.config)
        secrets = load_application_secrets()
    except (ForgeContactSyncConfigurationError, SecretConfigurationError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return EXIT_CONFIGURATION_ERROR

    if secrets.wavelog is None:
        print(
            "ERROR: ROLLING_THUNDER_WAVELOG_V2_TOKEN is required for Forge contact sync.",
            file=sys.stderr,
        )
        return EXIT_CONFIGURATION_ERROR

    try:
        repository = ForgeContactSyncRepository(config.storage.database_path)
        wavelog = WavelogClient(
            str(config.wavelog.base_url).rstrip("/"),
            secrets.wavelog.token,
            station_location_name=config.wavelog.station_location_name,
            station_logbook_name=config.wavelog.station_logbook_name,
            timeout_s=config.wavelog.request_timeout_s,
        )
        service = ForgeContactSyncService(repository, wavelog)
        ft8_performance_repository = ForgeFT8PerformanceRepository(
            config.storage.database_path
        )
        ft8_performance_service = ForgeFT8PerformanceService(
            ft8_performance_repository
        )
        application = ForgeContactSyncApiApplication(
            service,
            ft8_performance_service=ft8_performance_service,
        )
        server = ForgeContactHttpServer(
            config.server.bind_host,
            config.server.bind_port,
            application,
            logger=logger,
        )
    except (
        ForgeContactSyncStorageError,
        ForgeFT8PerformanceStorageError,
        OSError,
        ValueError,
    ) as error:
        logger.error("Forge contact synchronization service could not start: %s", error)
        return EXIT_RUNTIME_ERROR

    host, port = server.server_address
    logger.info(
        "Forge contact synchronization API listening on http://%s:%s; "
        "configured Wavelog target logbook=%r location=%r",
        host,
        port,
        config.wavelog.station_logbook_name,
        config.wavelog.station_location_name,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Forge contact synchronization service interrupted; shutting down.")
    except OSError as error:
        logger.error("Forge contact synchronization service failed: %s", error)
        return EXIT_RUNTIME_ERROR
    finally:
        server.close()
    return EXIT_SUCCESS


if __name__ == "__main__":
    raise SystemExit(main())
