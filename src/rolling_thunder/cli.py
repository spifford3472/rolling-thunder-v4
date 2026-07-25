"""Command-line operations for Rolling Thunder."""

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

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
    ContactAlreadyExistsError,
    ContactConflictError,
    ContactRepository,
)
from rolling_thunder.domain import Contact
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
EXIT_CONTACT_VALIDATION_ERROR = 8
EXIT_CONTACT_CONFLICT = 9
EXIT_CONTACT_NOT_FOUND = 10


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

    add_parser = subparsers.add_parser(
        "add-contact",
        help="Store one manually entered contact",
    )
    add_parser.add_argument(
        "callsign",
        help="contact callsign",
    )
    add_parser.add_argument(
        "--frequency-hz",
        required=True,
        help="contact frequency in integer hertz",
    )
    add_parser.add_argument(
        "--mode",
        required=True,
        help="radio mode: AM, CW, DATA, FM, LSB, or USB",
    )
    add_parser.add_argument(
        "--started-at",
        help=(
            "timezone-aware ISO-8601 start time "
            "(default: current UTC time)"
        ),
    )
    add_parser.add_argument(
        "--rst-sent",
        default="59",
        help="signal report sent (default: 59)",
    )
    add_parser.add_argument(
        "--rst-received",
        default="59",
        help="signal report received (default: 59)",
    )
    add_parser.add_argument(
        "--grid",
        help="optional Maidenhead grid",
    )
    add_parser.add_argument(
        "--notes",
        help="optional contact notes",
    )
    add_parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=(
            "YAML configuration path "
            f"(default: {DEFAULT_CONFIG_PATH})"
        ),
    )
    add_parser.add_argument(
        "--log",
        type=Path,
        default=DEFAULT_LOG_PATH,
        help=f"log file path (default: {DEFAULT_LOG_PATH})",
    )

    list_parser = subparsers.add_parser(
        "list-contacts",
        help="List recently stored contacts",
    )
    list_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="maximum contacts to list, from 1 through 1000 (default: 20)",
    )
    list_parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=(
            "YAML configuration path "
            f"(default: {DEFAULT_CONFIG_PATH})"
        ),
    )
    list_parser.add_argument(
        "--log",
        type=Path,
        default=DEFAULT_LOG_PATH,
        help=f"log file path (default: {DEFAULT_LOG_PATH})",
    )

    show_parser = subparsers.add_parser(
        "show-contact",
        help="Show one stored contact",
    )
    show_parser.add_argument(
        "contact_id",
        help="contact UUID",
    )
    show_parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=(
            "YAML configuration path "
            f"(default: {DEFAULT_CONFIG_PATH})"
        ),
    )
    show_parser.add_argument(
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


def run_manual_contact_entry(
    config_path: Path,
    *,
    callsign: str,
    frequency_hz: str,
    mode: str,
    started_at: str | None,
    rst_sent: str,
    rst_received: str,
    grid: str | None,
    notes: str | None,
    log_path: Path = DEFAULT_LOG_PATH,
) -> int:
    """Validate and store one manually entered contact."""
    logger = configure_logging(log_path)
    logger.info(
        "Manual contact entry requested callsign=%s frequency_hz=%s mode=%s",
        callsign,
        frequency_hz,
        mode,
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

    contact_values: dict[str, object] = {
        "callsign": callsign,
        "frequency_hz": frequency_hz,
        "mode": mode,
        "started_at": (
            started_at
            if started_at is not None
            else datetime.now(UTC)
        ),
        "rst_sent": rst_sent,
        "rst_received": rst_received,
        "grid": grid,
        "notes": notes,
    }

    try:
        contact = Contact.model_validate(contact_values)
    except ValidationError as error:
        logger.error("Contact validation error: %s", error)
        print(
            f"Rolling Thunder contact validation error: {error}",
            file=sys.stderr,
        )
        return EXIT_CONTACT_VALIDATION_ERROR

    try:
        repository = ContactRepository(
            config.storage.database_path
        )
        repository.add(contact)
    except ContactAlreadyExistsError as error:
        logger.error("Contact conflict: %s", error)
        print(
            f"Rolling Thunder contact conflict: {error}",
            file=sys.stderr,
        )
        return EXIT_CONTACT_CONFLICT
    except StorageError as error:
        logger.error("Storage error: %s", error)
        print(
            f"Rolling Thunder storage error: {error}",
            file=sys.stderr,
        )
        return EXIT_STORAGE_ERROR

    logger.info(
        "Manual contact entry completed contact_id=%s callsign=%s "
        "frequency_hz=%s mode=%s",
        contact.contact_id,
        contact.callsign,
        contact.frequency_hz,
        contact.mode.value,
    )
    print(
        "Contact created: "
        f"id={contact.contact_id} "
        f"callsign={contact.callsign} "
        f"frequency_hz={contact.frequency_hz} "
        f"mode={contact.mode.value} "
        f"started_at={contact.started_at.isoformat().replace('+00:00', 'Z')}"
    )
    return EXIT_SUCCESS


def format_contact_line(contact: Contact) -> str:
    """Format one contact as a stable, readable single line."""
    started_at = contact.started_at.isoformat().replace(
        "+00:00",
        "Z",
    )
    grid = str(contact.grid) if contact.grid is not None else "-"
    notes = json.dumps(
        contact.notes if contact.notes is not None else "",
        ensure_ascii=False,
    )

    return (
        f"id={contact.contact_id} "
        f"callsign={contact.callsign} "
        f"frequency_hz={contact.frequency_hz} "
        f"mode={contact.mode.value} "
        f"started_at={started_at} "
        f"rst={contact.rst_sent}/{contact.rst_received} "
        f"grid={grid} "
        f"sync={contact.synchronization_state.value} "
        f"notes={notes}"
    )


def run_contact_listing(
    config_path: Path,
    *,
    limit: int,
    log_path: Path = DEFAULT_LOG_PATH,
) -> int:
    """List recently stored contacts from newest to oldest."""
    logger = configure_logging(log_path)
    logger.info(
        "Contact listing requested config=%s limit=%s",
        config_path,
        limit,
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
        contacts = repository.list_recent(limit=limit)
    except (TypeError, ValueError) as error:
        logger.error("Contact list validation error: %s", error)
        print(
            f"Rolling Thunder contact validation error: {error}",
            file=sys.stderr,
        )
        return EXIT_CONTACT_VALIDATION_ERROR
    except StorageError as error:
        logger.error("Storage error: %s", error)
        print(
            f"Rolling Thunder storage error: {error}",
            file=sys.stderr,
        )
        return EXIT_STORAGE_ERROR

    logger.info(
        "Contact listing completed count=%s limit=%s",
        len(contacts),
        limit,
    )

    if not contacts:
        print("No contacts found.")
        return EXIT_SUCCESS

    for contact in contacts:
        print(format_contact_line(contact))

    return EXIT_SUCCESS


def format_contact_details(contact: Contact) -> str:
    """Format one contact as readable multiline details."""
    started_at = contact.started_at.isoformat().replace(
        "+00:00",
        "Z",
    )
    grid = str(contact.grid) if contact.grid is not None else "-"
    notes = contact.notes if contact.notes is not None else "-"

    return "\n".join(
        (
            f"Contact ID: {contact.contact_id}",
            f"Callsign: {contact.callsign}",
            f"Frequency: {contact.frequency_hz} Hz",
            f"Mode: {contact.mode.value}",
            f"Started: {started_at}",
            f"RST sent: {contact.rst_sent}",
            f"RST received: {contact.rst_received}",
            f"Grid: {grid}",
            f"Synchronization: {contact.synchronization_state.value}",
            f"Notes: {notes}",
        )
    )


def run_contact_show(
    config_path: Path,
    *,
    contact_id: str,
    log_path: Path = DEFAULT_LOG_PATH,
) -> int:
    """Show one stored contact by UUID."""
    logger = configure_logging(log_path)
    logger.info(
        "Contact lookup requested config=%s contact_id=%s",
        config_path,
        contact_id,
    )

    try:
        parsed_contact_id = UUID(contact_id)
    except ValueError as error:
        logger.error("Contact UUID validation error: %s", error)
        print(
            f"Rolling Thunder contact validation error: "
            f"invalid contact UUID: {contact_id}",
            file=sys.stderr,
        )
        return EXIT_CONTACT_VALIDATION_ERROR

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
        contact = repository.get(parsed_contact_id)
    except StorageError as error:
        logger.error("Storage error: %s", error)
        print(
            f"Rolling Thunder storage error: {error}",
            file=sys.stderr,
        )
        return EXIT_STORAGE_ERROR

    if contact is None:
        logger.error(
            "Contact not found contact_id=%s",
            parsed_contact_id,
        )
        print(
            f"Rolling Thunder contact not found: {parsed_contact_id}",
            file=sys.stderr,
        )
        return EXIT_CONTACT_NOT_FOUND

    logger.info(
        "Contact lookup completed contact_id=%s callsign=%s",
        contact.contact_id,
        contact.callsign,
    )
    print(format_contact_details(contact))
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

    if arguments.command == "add-contact":
        return run_manual_contact_entry(
            arguments.config,
            callsign=arguments.callsign,
            frequency_hz=arguments.frequency_hz,
            mode=arguments.mode,
            started_at=arguments.started_at,
            rst_sent=arguments.rst_sent,
            rst_received=arguments.rst_received,
            grid=arguments.grid,
            notes=arguments.notes,
            log_path=arguments.log,
        )

    if arguments.command == "list-contacts":
        return run_contact_listing(
            arguments.config,
            limit=arguments.limit,
            log_path=arguments.log,
        )

    if arguments.command == "show-contact":
        return run_contact_show(
            arguments.config,
            contact_id=arguments.contact_id,
            log_path=arguments.log,
        )

    parser.error(f"Unsupported command: {arguments.command}")
    return EXIT_CONFIGURATION_ERROR


if __name__ == "__main__":
    raise SystemExit(cli())
