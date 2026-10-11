"""Independent disabled-by-default Forge completed-QSO worker entry point."""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sqlite3
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Thread

from rolling_thunder.forge_ft8_attempt_api import FT8AttemptApiApplication
from rolling_thunder.forge_ft8_attempt_correlation import (
    AttemptInboxRepository,
    FT8AttemptCorrelationWorker,
    VoacapAttemptHistoryRepository,
    VoacapModelInput,
    VoacapProviderResult,
)
from rolling_thunder.forge_propagation_collectors import VoacapSummaryClient
from rolling_thunder.forge_propagation_history import (
    ForgePropagationHistoryRepository,
    PropagationHistoryStorageError,
)
from rolling_thunder.forge_propagation_qso_api import (
    CompletedQsoHttpServer,
    CompletedQsoIngestionApiApplication,
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
_INGESTION_TOKEN_ENV = "ROLLING_THUNDER_PROPAGATION_QSO_INGEST_TOKEN"


class _AttemptVoacapClient:
    def __init__(self, client: VoacapSummaryClient) -> None:
        self._client = client

    def predict(self, model_input: VoacapModelInput) -> VoacapProviderResult:
        return self._client.predict_attempt_input(model_input)


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
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Validate and print the provider-free execution plan",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Read the local worker status file without database or provider access",
    )
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
    inbox: CompletedQsoIngestionRepository | None = None,
) -> CompletedQsoWorkerOrchestrator:
    """Compose only worker-owned storage and the existing read-only VOACAP client."""
    inbox = inbox or build_inbox(config)
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


def build_inbox(config: ForgePropagationQsoWorkerConfig) -> CompletedQsoIngestionRepository:
    """Open only the service-owned durable ingestion store."""
    return CompletedQsoIngestionRepository(
        config.inbox_database_path,
        max_attempts=config.max_attempts,
        retry_base=timedelta(seconds=config.retry_base_s),
        retry_max=timedelta(seconds=config.retry_max_s),
    )


def _execution_plan(config: ForgePropagationQsoWorkerConfig) -> dict[str, object]:
    return {
        "enabled": config.enabled,
        "ingestion_enabled": config.ingestion_enabled,
        "voacap_enabled": config.voacap_enabled,
        "bind_host": config.bind_host,
        "bind_port": config.bind_port,
        "inbox_database_path": str(config.inbox_database_path),
        "history_database_path": str(config.history_database_path),
        "status_path": str(config.status_path),
        "worker_identity": config.worker_identity,
        "ingestion_token_environment": _INGESTION_TOKEN_ENV,
    }


def _print_status(path: Path) -> int:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(json.dumps({"status": "never_run", "status_path": str(path)}, sort_keys=True))
        return EXIT_SUCCESS
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        print(f"ERROR: cannot read completed-QSO worker status: {error}", file=sys.stderr)
        return EXIT_RUNTIME_ERROR
    print(json.dumps(payload, sort_keys=True))
    return EXIT_SUCCESS


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logger = configure_logging()
    try:
        config = load_forge_propagation_qso_worker_config(args.config)
    except ForgePropagationQsoWorkerConfigurationError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return EXIT_CONFIGURATION_ERROR

    if args.check_config:
        print(json.dumps(_execution_plan(config), sort_keys=True))
        return EXIT_SUCCESS
    if args.status:
        return _print_status(config.status_path)

    if not config.enabled:
        print("Forge completed-QSO propagation worker is disabled.")
        return EXIT_SUCCESS
    if not config.ingestion_enabled and not config.voacap_enabled:
        print("Forge completed-QSO ingestion and VOACAP correlation are disabled.")
        return EXIT_SUCCESS
    if args.once and not config.voacap_enabled:
        print("Forge completed-QSO VOACAP correlation is disabled.")
        return EXIT_SUCCESS

    ingestion_token = ""
    if config.ingestion_enabled and not args.once:
        ingestion_token = os.environ.get(_INGESTION_TOKEN_ENV, "")
        if len(ingestion_token) < 32:
            logger.error("%s must contain at least 32 characters", _INGESTION_TOKEN_ENV)
            return EXIT_CONFIGURATION_ERROR

    try:
        inbox = build_inbox(config)
        orchestrator = build_orchestrator(config, inbox) if config.voacap_enabled else None
        attempt_inbox = AttemptInboxRepository(
            config.inbox_database_path,
            max_attempts=config.max_attempts,
            retry_base=timedelta(seconds=config.retry_base_s),
            retry_max=timedelta(seconds=config.retry_max_s),
        )
        attempt_history = VoacapAttemptHistoryRepository(config.history_database_path)
        attempt_worker = (
            FT8AttemptCorrelationWorker(
                attempt_inbox,
                attempt_history,
                _AttemptVoacapClient(
                    VoacapSummaryClient(
                        str(config.voacap_base_url), timeout_s=config.provider_timeout_s
                    )
                ),
                worker_id=f"{config.worker_identity}-attempts",
                batch_size=config.batch_limit,
                lease_duration=timedelta(seconds=config.lease_duration_s),
            )
            if config.voacap_enabled
            else None
        )
    except (
        CompletedQsoIngestionError,
        PropagationHistoryStorageError,
        OSError,
        RuntimeError,
        ValueError,
        sqlite3.Error,
    ) as error:
        logger.error("Completed-QSO worker could not start: %s", error)
        return EXIT_RUNTIME_ERROR

    stop_event = Event()

    def request_stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    if not args.once:
        signal.signal(signal.SIGINT, request_stop)
        signal.signal(signal.SIGTERM, request_stop)

    server: CompletedQsoHttpServer | None = None
    server_thread: Thread | None = None
    server_failed = Event()
    if config.ingestion_enabled and not args.once:
        try:
            application = CompletedQsoIngestionApiApplication(
                inbox,
                bearer_token=ingestion_token,
                ingestion_enabled=True,
                voacap_enabled=config.voacap_enabled,
                attempt_application=FT8AttemptApiApplication(
                    attempt_inbox,
                    attempt_history,
                    bearer_token=ingestion_token,
                    ingestion_enabled=True,
                ),
            )
            server = CompletedQsoHttpServer(
                config.bind_host,
                config.bind_port,
                application,
                request_timeout_s=config.request_timeout_s,
                max_connections=config.max_connections,
                logger=logger,
            )
        except (OSError, ValueError) as error:
            logger.error("Completed-QSO ingestion API could not start: %s", error)
            return EXIT_RUNTIME_ERROR

        def serve_ingestion() -> None:
            try:
                assert server is not None
                server.serve_forever()
            except OSError as error:
                logger.error("Completed-QSO ingestion API failed: %s", error)
                server_failed.set()
                stop_event.set()

        server_thread = Thread(
            target=serve_ingestion,
            name="completed-qso-ingestion-api",
            daemon=True,
        )
        server_thread.start()
        logger.info(
            "Completed-QSO ingestion API listening on http://%s:%s",
            *server.server_address,
        )

    logger.info(
        "Completed-QSO service started identity=%s batch_limit=%s lease_duration_s=%s "
        "ingestion_enabled=%s voacap_enabled=%s",
        config.worker_identity,
        config.batch_limit,
        config.lease_duration_s,
        config.ingestion_enabled,
        config.voacap_enabled,
    )
    try:
        while not stop_event.is_set():
            if orchestrator is not None:
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
            if attempt_worker is not None:
                attempt_completed, attempt_failed = attempt_worker.run_once(
                    now_utc=datetime.now(UTC)
                )
                logger.info(
                    "attempts_completed=%s attempts_failed=%s",
                    attempt_completed,
                    attempt_failed,
                )
            if args.once or stop_event.wait(config.poll_interval_s):
                break
        if server_failed.is_set():
            return EXIT_RUNTIME_ERROR
    except (CompletedQsoIngestionError, PropagationHistoryStorageError, OSError, ValueError) as error:
        logger.error("Completed-QSO worker cycle failed: %s", error)
        return EXIT_RUNTIME_ERROR
    finally:
        if server is not None:
            server.shutdown()
            server.close()
        if server_thread is not None:
            server_thread.join(timeout=5)
    logger.info("Completed-QSO worker stopped identity=%s", config.worker_identity)
    return EXIT_SUCCESS


if __name__ == "__main__":
    raise SystemExit(main())
