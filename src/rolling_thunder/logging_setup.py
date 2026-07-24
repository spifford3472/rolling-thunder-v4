"""Application logging configuration for Rolling Thunder."""

import logging
from pathlib import Path

DEFAULT_LOG_PATH = Path("data/rolling-thunder.log")
LOGGER_NAME = "rolling_thunder"


def configure_logging(log_path: Path = DEFAULT_LOG_PATH) -> logging.Logger:
    """Configure and return the Rolling Thunder application logger."""
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    for handler in logger.handlers:
        handler.close()

    logger.handlers.clear()

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
        )
    )
    logger.addHandler(file_handler)

    return logger
