"""Independent disabled-by-default Forge completed-QSO worker entry point."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path
from threading import Event

from rolling_thunder.forge_propagation_collectors import VoacapSummaryClient
from rolling_thunder.forge_propagation_history import (
    ForgePropagationHistoryRepository,
    PropagationHistoryStorageError,
)
from rolling_thunder.forge_propagation_qso_ingestion import (
    CompletedQsoCorrelationWorker,
    CompletedQsoIngestionError,
    CompletedQsoIngestionRepository,
    VoacapCompletedQsoCorrelator,
)
from rolling_thunder.forge_propagation_qso_worker import (
    CompletedQsoWorkerOrchestrator,
    JsonFileCompletedQsoWorkerStatusPublisher,
)
from rolling_thunder.forge_propagation_qso_worker_config import (
    ForgePropagationQsoWorkerConfig,
    ForgePropagationQsoWorkerConfigurationError,
    load_forge_propagation_qso_worker_config,
)

DEFAULT_CONFIG_PATH = Path("config/forge-propagation-qso-worker.yaml")
EXIT_SUCCESS = 0
EXIT_CONFIGURATION_ERROR = 2
EXIT_RUNTIME_ERROR = 3
_LOGGER_NAME = "rolling_thunder.forge_propagation_qso_worker"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rolling-thunder-forge-propagation-qso-worker",
        description="Forge-local completed-QSO VOACAP correlation worker",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"Configuration path (default: {DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument("--once", action="store_true", help="Run one bounded cycle and exit")
    return parser


def configure_logging() -> logging.Logger:
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in logger.handlers:
        handler.close()
    logger.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(handler)
    return logger


def build_orchestrator(
    config: ForgePropagationQsoWorkerConfig,
) -> CompletedQsoWorkerOrchestrator:
    """Compose only worker-owned storage and the existing read-only VOACAP client."""
    inbox = CompletedQsoIngestionRepository(
        config.inbox_database_path,
        max_attempts=config.max_attempts,
        retry_base=timedelta(seconds=config.retry_base_s),
        retry_max=timedelta(seconds=config.retry_max_s),
    )
    history = ForgePropagationHistoryRepository(config.history_database_path)
    client = VoacapSummaryClient(
        str(config.voacap_base_url), timeout_s=config.provider_timeout_s
    )
    correlator = VoacapCompletedQsoCorrelator(history, client)
    worker = CompletedQsoCorrelationWorker(
        inbox,
        correlator,
        worker_identity=config.worker_identity,
        batch_limit=config.batch_limit,
        lease_duration=timedelta(seconds=config.lease_duration_s),
    )
    return CompletedQsoWorkerOrchestrator(
        inbox,
        worker,
        worker_identity=config.worker_identity,
        publisher=JsonFileCompletedQsoWorkerStatusPublisher(config.status_path),
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logger = configure_logging()
    try:
        config = load_forge_propagation_qso_worker_config(args.config)
    except ForgePropagationQsoWorkerConfigurationError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return EXIT_CONFIGURATION_ERROR

    if not config.enabled:
        print("Forge completed-QSO propagation worker is disabled.")
        return EXIT_SUCCESS
    if not config.voacap_enabled:
        print("Forge completed-QSO VOACAP correlation is disabled.")
        return EXIT_SUCCESS

    try:
        orchestrator = build_orchestrator(config)
    except (CompletedQsoIngestionError, PropagationHistoryStorageError, OSError, ValueError) as error:
        logger.error("Completed-QSO worker could not start: %s", error)
        return EXIT_RUNTIME_ERROR

    stop_event = Event()

    def request_stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    if not args.once:
        signal.signal(signal.SIGINT, request_stop)
        signal.signal(signal.SIGTERM, request_stop)

    logger.info(
        "Completed-QSO worker started identity=%s batch_limit=%s lease_duration_s=%s",
        config.worker_identity,
        config.batch_limit,
        config.lease_duration_s,
    )
    try:
        while not stop_event.is_set():
            snapshot = orchestrator.run_once()
            logger.info(
                "cycle=%s processed=%s due=%s pending=%s retry=%s dead_letter=%s",
                snapshot.cycle_state.value,
                len(snapshot.results),
                snapshot.queue.due_count,
                snapshot.queue.pending_count,
                snapshot.queue.retry_count,
                snapshot.queue.dead_letter_count,
            )
            if args.once or stop_event.wait(config.poll_interval_s):
                break
    except (CompletedQsoIngestionError, PropagationHistoryStorageError, OSError, ValueError) as error:
        logger.error("Completed-QSO worker cycle failed: %s", error)
        return EXIT_RUNTIME_ERROR
    logger.info("Completed-QSO worker stopped identity=%s", config.worker_identity)
    return EXIT_SUCCESS


if __name__ == "__main__":
    raise SystemExit(main())
