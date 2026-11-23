"""Application logging configuration for Rolling Thunder."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

DEFAULT_LOG_PATH = Path("data/rolling-thunder.log")
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 5
LOGGER_NAME = "rolling_thunder"
WSPR_LOGGER_NAME = "rolling_thunder.wspr_receive"
WSPR_LOG_PATH = Path("data/rolling-thunder-wspr-debug.log")
WSPR_LOG_MAX_BYTES = 1024 * 1024
WSPR_LOG_BACKUP_COUNT = 3


def configure_logging(
    log_path: Path = DEFAULT_LOG_PATH,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    backup_count: int = DEFAULT_BACKUP_COUNT,
) -> logging.Logger:
    """Configure and return the Rolling Thunder application logger."""
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    for handler in logger.handlers:
        handler.close()

    logger.handlers.clear()

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
        )
    )
    logger.addHandler(file_handler)

    return logger


def configure_wspr_logging(
    log_path: Path = WSPR_LOG_PATH,
    *,
    max_bytes: int = WSPR_LOG_MAX_BYTES,
    backup_count: int = WSPR_LOG_BACKUP_COUNT,
) -> logging.Logger:
    """Configure an isolated, bounded logger for identity-free WSPR diagnostics."""
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(WSPR_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    for handler in logger.handlers:
        handler.close()
    logger.handlers.clear()

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    logger.addHandler(file_handler)
    return logger
