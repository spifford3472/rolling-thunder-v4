"""Standalone, undeployed Forge propagation-history collector entry point."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from rolling_thunder.forge_propagation_collectors import (
    ForgePropagationHistoryService,
    HamQslSolarCollector,
    Kc2gGeoJsonCollector,
    VoacapSummaryClient,
)
from rolling_thunder.forge_propagation_config import (
    ForgePropagationConfigurationError,
    load_forge_propagation_config,
)
from rolling_thunder.forge_propagation_history import ForgePropagationHistoryRepository


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rolling-thunder-forge-propagation")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--once", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one collection cycle; lifecycle supervision is intentionally not deployed."""
    args = build_parser().parse_args(argv)
    try:
        config = load_forge_propagation_config(args.config)
    except ForgePropagationConfigurationError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    if not config.enabled:
        print("Forge propagation history is disabled.")
        return 0
    repository = ForgePropagationHistoryRepository(config.database_path)
    service = ForgePropagationHistoryService(
        repository,
        HamQslSolarCollector(timeout_s=config.provider_timeout_s),
        Kc2gGeoJsonCollector(timeout_s=config.provider_timeout_s),
        VoacapSummaryClient(
            str(config.voacap_base_url), timeout_s=config.provider_timeout_s
        ),
        minimum_collection_interval=timedelta(seconds=config.collection_interval_s),
    )
    results = service.collect_due(datetime.now(UTC))
    print(" ".join(f"{name}={result}" for name, result in sorted(results.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
