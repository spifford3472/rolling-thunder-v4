"""Rolling Thunder application entry point."""

import sys
from pathlib import Path

from rolling_thunder.config import ConfigurationError, load_config
from rolling_thunder.logging_setup import DEFAULT_LOG_PATH, configure_logging

DEFAULT_CONFIG_PATH = Path("config/rolling-thunder.yaml")


def main(
    config_path: Path = DEFAULT_CONFIG_PATH,
    log_path: Path = DEFAULT_LOG_PATH,
) -> int:
    """Start Rolling Thunder after loading validated configuration."""
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

    print(
        "Rolling Thunder v4 starting "
        f"for {config.operator.callsign} "
        f"with mock hardware={config.hardware.mock}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
