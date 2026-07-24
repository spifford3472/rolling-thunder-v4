"""Rolling Thunder application entry point."""

import sys
from pathlib import Path

from rolling_thunder.config import ConfigurationError, load_config

DEFAULT_CONFIG_PATH = Path("config/rolling-thunder.yaml")


def main(config_path: Path = DEFAULT_CONFIG_PATH) -> int:
    """Start Rolling Thunder after loading validated configuration."""
    try:
        config = load_config(config_path)
    except ConfigurationError as error:
        print(f"Rolling Thunder configuration error: {error}", file=sys.stderr)
        return 2

    print(
        "Rolling Thunder v4 starting "
        f"for {config.operator.callsign} "
        f"with mock hardware={config.hardware.mock}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
