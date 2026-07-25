"""Rolling Thunder application entry point."""

import sys
from pathlib import Path

from rolling_thunder.config import (
    ConfigurationError,
    load_config,
    resolve_contact_backup_directory,
)
from rolling_thunder.logging_setup import DEFAULT_LOG_PATH, configure_logging
from rolling_thunder.storage import StorageError, initialize_database

DEFAULT_CONFIG_PATH = Path("config/rolling-thunder.yaml")


def main(
    config_path: Path = DEFAULT_CONFIG_PATH,
    log_path: Path = DEFAULT_LOG_PATH,
) -> int:
    """Start Rolling Thunder after loading configuration and local storage."""
    logger = configure_logging(log_path)
    logger.info("Application startup requested")

    try:
        config = load_config(config_path)
    except ConfigurationError as error:
        logger.error("Configuration error: %s", error)
        print(f"Rolling Thunder configuration error: {error}", file=sys.stderr)
        return 2

    logger.info(
        "Configuration loaded for operator=%s mock_hardware=%s",
        config.operator.callsign,
        config.hardware.mock,
    )

    backup_directory = resolve_contact_backup_directory(
        config,
        config_path,
    )
    logger.info(
        "Contact backups configured enabled=%s directory=%s retention=%s",
        config.storage.contact_backups.enabled,
        backup_directory,
        config.storage.contact_backups.retention_count,
    )

    try:
        schema_version = initialize_database(config.storage.database_path)
    except StorageError as error:
        logger.error("Storage error: %s", error)
        print(f"Rolling Thunder storage error: {error}", file=sys.stderr)
        return 3

    logger.info(
        "Local storage initialized database=%s schema_version=%s",
        config.storage.database_path,
        schema_version,
    )

    print(
        "Rolling Thunder v4 starting "
        f"for {config.operator.callsign} "
        f"with mock hardware={config.hardware.mock}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
