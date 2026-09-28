"""Tests for Rolling Thunder logging configuration."""

import logging
from pathlib import Path

from rolling_thunder.logging_setup import configure_logging


def test_logging_rotates_when_size_limit_is_reached(tmp_path: Path) -> None:
    """Logging should rotate files after reaching the configured size."""
    log_path = tmp_path / "rolling-thunder.log"
    logger = configure_logging(
        log_path,
        max_bytes=120,
        backup_count=2,
    )

    for index in range(20):
        logger.info("rotation test message number %s", index)

    for handler in logger.handlers:
        handler.flush()

    assert log_path.is_file()
    assert (tmp_path / "rolling-thunder.log.1").is_file()

    combined_text = "".join(
        path.read_text(encoding="utf-8")
        for path in sorted(tmp_path.glob("rolling-thunder.log*"))
    )
    assert "rotation test message" in combined_text


def test_logging_limits_backup_count(tmp_path: Path) -> None:
    """Logging should retain no more than the configured number of backups."""
    log_path = tmp_path / "rolling-thunder.log"
    logger = configure_logging(
        log_path,
        max_bytes=80,
        backup_count=2,
    )

    for index in range(50):
        logger.info("backup count test message number %s", index)

    for handler in logger.handlers:
        handler.flush()

    backups = list(tmp_path.glob("rolling-thunder.log.*"))

    assert len(backups) == 2


def test_configure_logging_replaces_existing_handlers(tmp_path: Path) -> None:
    """Repeated configuration should not duplicate log output."""
    first_log_path = tmp_path / "first.log"
    second_log_path = tmp_path / "second.log"

    logger = configure_logging(first_log_path)
    original_handlers = list(logger.handlers)

    logger = configure_logging(second_log_path)

    assert len(logger.handlers) == 1
    assert logger.handlers != original_handlers
    assert isinstance(logger.handlers[0], logging.Handler)
