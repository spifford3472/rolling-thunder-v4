"""Standalone supervised Forge propagation environmental collector."""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import FrameType
from typing import Any

from rolling_thunder.forge_propagation_collectors import (
    HAMQSL_SOLAR_URL,
    KC2G_FOF2_URL,
    KC2G_MUFD_URL,
    ForgePropagationHistoryService,
    HamQslSolarCollector,
    Kc2gGeoJsonCollector,
    VoacapSummaryClient,
)
from rolling_thunder.forge_propagation_config import (
    ForgePropagationConfigurationError,
    load_forge_propagation_config,
)
from rolling_thunder.forge_propagation_history import (
    ForgePropagationHistoryRepository,
    PropagationHistoryStorageError,
)
from rolling_thunder.forge_propagation_runtime import ForgePropagationCollectionRuntime

DEFAULT_CONFIG_PATH = Path("config/forge-propagation.yaml")
EXIT_SUCCESS = 0
EXIT_CONFIGURATION_ERROR = 2
EXIT_RUNTIME_ERROR = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rolling-thunder-forge-propagation",
        description="Forge HamQSL and KC2G propagation environmental collector",
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    operation = parser.add_mutually_exclusive_group()
    operation.add_argument("--once", action="store_true")
    operation.add_argument(
        "--status",
        action="store_true",
        help="print durable provider health as JSON without provider requests",
    )
    operation.add_argument(
        "--check-config",
        action="store_true",
        help="validate and print the collection plan without database or provider access",
    )
    return parser


def configure_logging() -> logging.Logger:
    logger = logging.getLogger("rolling_thunder.forge_propagation")
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
    """Run once, report status, or remain active under an external supervisor."""
    args = build_parser().parse_args(argv)
    logger = configure_logging()
    try:
        config = load_forge_propagation_config(args.config)
    except ForgePropagationConfigurationError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return EXIT_CONFIGURATION_ERROR
    if args.check_config:
        print(
            json.dumps(
                {
                    "enabled": config.enabled,
                    "database_path": str(config.database_path),
                    "collection_interval_s": config.collection_interval_s,
                    "provider_timeout_s": config.provider_timeout_s,
                    "providers": [HAMQSL_SOLAR_URL, KC2G_MUFD_URL, KC2G_FOF2_URL],
                    "qso_enrichment": {
                        "voacap_enabled": config.voacap_enabled,
                        "weather_enrichment_enabled": config.weather_enrichment_enabled,
                        "pskreporter_enabled": config.pskreporter.enabled,
                    },
                },
                sort_keys=True,
            )
        )
        return EXIT_SUCCESS
    if not config.enabled and not args.status:
        print("Forge propagation history is disabled.")
        return EXIT_SUCCESS
    try:
        repository = ForgePropagationHistoryRepository(config.database_path)
        service = ForgePropagationHistoryService(
            repository,
            HamQslSolarCollector(timeout_s=config.provider_timeout_s),
            Kc2gGeoJsonCollector(timeout_s=config.provider_timeout_s),
            VoacapSummaryClient(
                str(config.voacap_base_url), timeout_s=config.provider_timeout_s
            ),
            minimum_collection_interval=timedelta(seconds=config.collection_interval_s),
            retry_initial_backoff=timedelta(seconds=config.retry_initial_backoff_s),
            retry_maximum_backoff=timedelta(seconds=config.retry_maximum_backoff_s),
        )
        if args.status:
            payload = service.get_health(datetime.now(UTC)).model_dump_json()
            print(payload)
            return EXIT_SUCCESS
        if args.once:
            results = service.collect_due(datetime.now(UTC))
            print(" ".join(f"{name}={result}" for name, result in sorted(results.items())))
            return EXIT_SUCCESS

        runtime = ForgePropagationCollectionRuntime(
            service,
            check_interval_s=config.scheduler_check_interval_s,
            logger=logger,
        )
        previous_handlers: dict[
            signal.Signals, Callable[[int, FrameType | None], Any] | int | None
        ] = {}
        for handled_signal in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[handled_signal] = signal.signal(
                handled_signal, lambda _signum, _frame: runtime.stop()
            )
        logger.info(
            "Forge propagation collector started; database=%s interval_s=%s",
            config.database_path,
            config.collection_interval_s,
        )
        try:
            runtime.run_forever()
        finally:
            for handled_signal, previous_handler in previous_handlers.items():
                signal.signal(handled_signal, previous_handler)
        logger.info("Forge propagation collector stopped.")
        return EXIT_SUCCESS
    except (OSError, PropagationHistoryStorageError, ValueError) as error:
        logger.error("Forge propagation collector failed: %s", error)
        return EXIT_RUNTIME_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
