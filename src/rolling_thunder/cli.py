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
from rolling_thunder.contact_import import (
    ContactImportError,
    import_contacts_from_json,
    preview_contact_import,
)
from rolling_thunder.contact_repository import (
    ContactConflictError,
    ContactRepository,
)
from rolling_thunder.logging_setup import DEFAULT_LOG_PATH, configure_logging
from rolling_thunder.main import DEFAULT_CONFIG_PATH
from rolling_thunder.storage import StorageError

EXIT_SUCCESS = 0
EXIT_CONFIGURATION_ERROR = 2
EXIT_STORAGE_ERROR = 3
EXIT_BACKUP_ERROR = 4
EXIT_BACKUP_DISABLED = 5
EXIT_IMPORT_VALIDATION_ERROR = 6
EXIT_IMPORT_CONFLICT = 7


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

    restore_parser = subparsers.add_parser(
        "restore-contacts",
        help="Validate or restore contacts from a backup",
    )
    restore_parser.add_argument(
        "backup",
        type=Path,
        help="contact backup JSON path",
    )
    restore_parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=(
            "YAML configuration path "
            f"(default: {DEFAULT_CONFIG_PATH})"
        ),
    )
    restore_parser.add_argument(
        "--log",
        type=Path,
        default=DEFAULT_LOG_PATH,
        help=f"log file path (default: {DEFAULT_LOG_PATH})",
    )
    restore_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate and report changes without modifying the database",
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


def run_manual_contact_restore(
    config_path: Path,
    backup_path: Path,
    *,
    dry_run: bool,
    log_path: Path = DEFAULT_LOG_PATH,
) -> int:
    """Validate or transactionally restore contacts from one backup."""
    logger = configure_logging(log_path)
    logger.info(
        "Manual contact restore requested config=%s backup=%s dry_run=%s",
        config_path,
        backup_path,
        dry_run,
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
        preview = preview_contact_import(
            repository,
            backup_path,
        )
    except ContactImportError as error:
        logger.error("Contact restore validation error: %s", error)
        print(
            f"Rolling Thunder contact restore validation error: {error}",
            file=sys.stderr,
        )
        return EXIT_IMPORT_VALIDATION_ERROR
    except StorageError as error:
        logger.error("Storage error: %s", error)
        print(
            f"Rolling Thunder storage error: {error}",
            file=sys.stderr,
        )
        return EXIT_STORAGE_ERROR

    if dry_run:
        logger.info(
            "Contact restore dry run completed imported=%s skipped=%s "
            "conflicted=%s",
            preview.imported,
            preview.skipped,
            preview.conflicted,
        )
        print(
            "Contact restore dry run: "
            f"imported={preview.imported} "
            f"skipped={preview.skipped} "
            f"conflicted={preview.conflicted}"
        )
        return (
            EXIT_IMPORT_CONFLICT
            if preview.conflicted
            else EXIT_SUCCESS
        )

    if preview.conflicted:
        message = (
            "Contact restore contains "
            f"{preview.conflicted} conflicting contact(s)."
        )
        logger.error("Contact restore conflict: %s", message)
        print(
            f"Rolling Thunder contact restore conflict: {message}",
            file=sys.stderr,
        )
        return EXIT_IMPORT_CONFLICT

    try:
        result = import_contacts_from_json(
            repository,
            backup_path,
        )
    except ContactConflictError as error:
        logger.error("Contact restore conflict: %s", error)
        print(
            f"Rolling Thunder contact restore conflict: {error}",
            file=sys.stderr,
        )
        return EXIT_IMPORT_CONFLICT
    except ContactImportError as error:
        logger.error("Contact restore error: %s", error)
        print(
            f"Rolling Thunder contact restore error: {error}",
            file=sys.stderr,
        )
        return EXIT_IMPORT_VALIDATION_ERROR
    except StorageError as error:
        logger.error("Storage error: %s", error)
        print(
            f"Rolling Thunder storage error: {error}",
            file=sys.stderr,
        )
        return EXIT_STORAGE_ERROR

    logger.info(
        "Manual contact restore completed imported=%s skipped=%s",
        result.imported,
        result.skipped,
    )
    print(
        "Contact restore completed: "
        f"imported={result.imported} "
        f"skipped={result.skipped} "
        "conflicted=0"
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

    if arguments.command == "restore-contacts":
        return run_manual_contact_restore(
            arguments.config,
            arguments.backup,
            dry_run=arguments.dry_run,
            log_path=arguments.log,
        )

    parser.error(f"Unsupported command: {arguments.command}")
    return EXIT_CONFIGURATION_ERROR


if __name__ == "__main__":
    raise SystemExit(cli())
