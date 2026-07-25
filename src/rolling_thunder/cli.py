"""Command-line operations for Rolling Thunder."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from rolling_thunder.config import (
    ConfigurationError,
    load_config,
    resolve_contact_backup_directory,
)
from rolling_thunder.contact_backup import (
    ContactBackupError,
    create_contact_backup,
)
from rolling_thunder.contact_repository import ContactRepository
from rolling_thunder.logging_setup import DEFAULT_LOG_PATH, configure_logging
from rolling_thunder.main import DEFAULT_CONFIG_PATH
from rolling_thunder.storage import StorageError

EXIT_SUCCESS = 0
EXIT_CONFIGURATION_ERROR = 2
EXIT_STORAGE_ERROR = 3
EXIT_BACKUP_ERROR = 4
EXIT_BACKUP_DISABLED = 5


def build_parser() -> argparse.ArgumentParser:
    """Build the Rolling Thunder command-line parser."""
    parser = argparse.ArgumentParser(
        prog="rolling-thunder",
        description="Rolling Thunder mobile amateur-radio console",
    )
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    backup_parser = subparsers.add_parser(
        "backup-contacts",
        help="Create one verified local contact backup",
    )
    backup_parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=(
            "YAML configuration path "
            f"(default: {DEFAULT_CONFIG_PATH})"
        ),
    )
    backup_parser.add_argument(
        "--log",
        type=Path,
        default=DEFAULT_LOG_PATH,
        help=f"log file path (default: {DEFAULT_LOG_PATH})",
    )

    return parser


def run_manual_contact_backup(
    config_path: Path,
    log_path: Path = DEFAULT_LOG_PATH,
) -> int:
    """Create one configured contact backup and report the result."""
    logger = configure_logging(log_path)
    logger.info(
        "Manual contact backup requested config=%s",
        config_path,
    )

    try:
        config = load_config(config_path)
    except ConfigurationError as error:
        logger.error("Configuration error: %s", error)
        print(
            f"Rolling Thunder configuration error: {error}",
            file=sys.stderr,
        )
        return EXIT_CONFIGURATION_ERROR

    backup_config = config.storage.contact_backups

    if not backup_config.enabled:
        message = (
            "Contact backups are disabled. Set "
            "storage.contact_backups.enabled to true."
        )
        logger.error("Manual contact backup rejected: %s", message)
        print(
            f"Rolling Thunder contact backup error: {message}",
            file=sys.stderr,
        )
        return EXIT_BACKUP_DISABLED

    backup_directory = resolve_contact_backup_directory(
        config,
        config_path,
    )

    try:
        repository = ContactRepository(
            config.storage.database_path
        )
    except StorageError as error:
        logger.error("Storage error: %s", error)
        print(
            f"Rolling Thunder storage error: {error}",
            file=sys.stderr,
        )
        return EXIT_STORAGE_ERROR

    try:
        result = create_contact_backup(
            repository,
            backup_directory,
            retention_count=backup_config.retention_count,
        )
    except (ContactBackupError, StorageError) as error:
        logger.error("Contact backup error: %s", error)
        print(
            f"Rolling Thunder contact backup error: {error}",
            file=sys.stderr,
        )
        return EXIT_BACKUP_ERROR

    logger.info(
        "Manual contact backup completed path=%s contacts=%s",
        result.path,
        result.contact_count,
    )
    print(
        "Contact backup created: "
        f"{result.path} "
        f"(contacts: {result.contact_count})"
    )
    return EXIT_SUCCESS


def cli(argv: Sequence[str] | None = None) -> int:
    """Parse command-line arguments and execute the selected operation."""
    parser = build_parser()
    arguments = parser.parse_args(argv)

    if arguments.command == "backup-contacts":
        return run_manual_contact_backup(
            arguments.config,
            arguments.log,
        )

    parser.error(f"Unsupported command: {arguments.command}")
    return EXIT_CONFIGURATION_ERROR


if __name__ == "__main__":
    raise SystemExit(cli())
