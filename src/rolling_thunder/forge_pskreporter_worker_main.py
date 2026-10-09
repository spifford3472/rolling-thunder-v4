"""Independent disabled-by-default Forge PSK Reporter worker service."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from json import dumps
from pathlib import Path
from threading import Event, Thread

from pydantic import ValidationError

from rolling_thunder.forge_propagation_history import (
    ForgePropagationHistoryRepository,
    PropagationHistoryStorageError,
)
from rolling_thunder.forge_pskreporter import PskReporterHttpClient
from rolling_thunder.forge_pskreporter_orchestration import (
    PskReporterCompletedEventAdapter,
    PskReporterOrchestrationError,
    PskReporterOrchestrationRepository,
    PskReporterOrchestrationWorker,
)
from rolling_thunder.forge_pskreporter_worker import (
    ForgePskReporterApiApplication,
    ForgePskReporterHttpServer,
    ForgePskReporterScheduler,
    ForgePskReporterWorkerRuntime,
    ForgePskReporterWorkerSnapshot,
    JsonFilePskReporterWorkerStatusPublisher,
)
from rolling_thunder.forge_pskreporter_worker_config import (
    ForgePskReporterWorkerConfig,
    ForgePskReporterWorkerConfigurationError,
    load_forge_pskreporter_worker_config,
)

DEFAULT_CONFIG_PATH = Path("config/forge-pskreporter-worker.yaml")
EXIT_SUCCESS = 0
EXIT_CONFIGURATION_ERROR = 2
EXIT_RUNTIME_ERROR = 3
_LOGGER_NAME = "rolling_thunder.forge_pskreporter_worker"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rolling-thunder-forge-pskreporter-worker",
        description="Authenticated Forge completed-FT8 PSK Reporter analysis service",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"Configuration path (default: {DEFAULT_CONFIG_PATH})",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check-config",
        action="store_true",
        help="Validate and print the provider-free service plan",
    )
    mode.add_argument(
        "--status",
        action="store_true",
        help="Print the last local status file without database or provider access",
    )
    mode.add_argument("--once", action="store_true", help="Run one bounded worker cycle")
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


def config_plan(config: ForgePskReporterWorkerConfig) -> dict[str, object]:
    """Return a non-secret plan suitable for preflight and rollout review."""
    return {
        "service": "forge-pskreporter-worker",
        "enabled": config.enabled,
        "ingestion_enabled": config.ingestion_enabled,
        "provider_enabled": config.pskreporter.enabled,
        "bind_host": config.server.bind_host,
        "bind_port": config.server.bind_port,
        "orchestration_database_path": str(config.orchestration_database_path),
        "history_database_path": str(config.history_database_path),
        "status_path": str(config.status_path),
        "scheduler_interval_s": config.scheduler_interval_s,
        "minimum_query_interval_s": config.pskreporter.minimum_query_interval_s,
        "report_latency_s": config.pskreporter.report_latency_s,
        "maximum_qsos_per_query": config.pskreporter.maximum_qsos_per_query,
        "bearer_token_environment": config.bearer_token_environment,
    }


def build_runtime(
    config: ForgePskReporterWorkerConfig,
) -> tuple[
    PskReporterOrchestrationRepository,
    PskReporterCompletedEventAdapter,
    ForgePskReporterWorkerRuntime,
]:
    """Compose only the PSK service's isolated databases and official provider client."""
    orchestration = PskReporterOrchestrationRepository(config.orchestration_database_path)
    history = ForgePropagationHistoryRepository(config.history_database_path)
    worker = PskReporterOrchestrationWorker(
        orchestration,
        history,
        config.pskreporter,
        client=PskReporterHttpClient(config.pskreporter),
    )
    runtime = ForgePskReporterWorkerRuntime(
        worker,
        orchestration,
        ingestion_enabled=config.ingestion_enabled,
        provider_enabled=config.pskreporter.enabled,
        minimum_interval=config.pskreporter.minimum_query_interval,
        publisher=JsonFilePskReporterWorkerStatusPublisher(config.status_path),
    )
    return orchestration, PskReporterCompletedEventAdapter(
        orchestration, config.pskreporter
    ), runtime


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logger = configure_logging()
    try:
        config = load_forge_pskreporter_worker_config(args.config)
    except ForgePskReporterWorkerConfigurationError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return EXIT_CONFIGURATION_ERROR

    if args.check_config:
        print(dumps(config_plan(config), sort_keys=True))
        return EXIT_SUCCESS
    if args.status:
        return _print_status(config.status_path)
    if not config.enabled:
        print("Forge PSK Reporter worker service is disabled.")
        return EXIT_SUCCESS

    bearer_token: str | None = None
    if config.ingestion_enabled:
        bearer_token = os.environ.get(config.bearer_token_environment)
        if (
            bearer_token is None
            or len(bearer_token) < 32
            or any(character.isspace() for character in bearer_token)
        ):
            print(
                f"ERROR: {config.bearer_token_environment} must contain at least 32 ",
                "non-whitespace characters with no whitespace when ingestion is enabled.",
                sep="",
                file=sys.stderr,
            )
            return EXIT_CONFIGURATION_ERROR

    try:
        orchestration, sink, runtime = build_runtime(config)
    except (
        OSError,
        ValueError,
        PskReporterOrchestrationError,
        PropagationHistoryStorageError,
    ) as error:
        logger.error("Forge PSK Reporter worker could not start: %s", error)
        return EXIT_RUNTIME_ERROR

    if args.once:
        try:
            snapshot = runtime.run_once()
        except (OSError, ValueError, PskReporterOrchestrationError) as error:
            logger.error("Forge PSK Reporter worker cycle failed: %s", error)
            return EXIT_RUNTIME_ERROR
        print(snapshot.model_dump_json())
        return EXIT_SUCCESS

    try:
        application = ForgePskReporterApiApplication(
            sink,
            lambda: _current_snapshot(config, orchestration, runtime),
            ingestion_enabled=config.ingestion_enabled,
            bearer_token=bearer_token,
        )
        server = ForgePskReporterHttpServer(
            config.server.bind_host,
            config.server.bind_port,
            application,
            maximum_event_bytes=config.server.maximum_event_bytes,
            logger=logger,
        )
        scheduler = ForgePskReporterScheduler(
            runtime,
            interval_s=config.scheduler_interval_s,
            logger=logger,
        )
    except (
        OSError,
        ValueError,
        PskReporterOrchestrationError,
        PropagationHistoryStorageError,
    ) as error:
        logger.error("Forge PSK Reporter worker could not start: %s", error)
        return EXIT_RUNTIME_ERROR

    stop_event = Event()

    def request_stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    host, port = server.server_address
    logger.info(
        "Forge PSK Reporter service listening on http://%s:%s ingestion=%s provider=%s",
        host,
        port,
        config.ingestion_enabled,
        config.pskreporter.enabled,
    )
    server_thread = Thread(target=server.serve_forever, name="forge-pskreporter-api")
    scheduler_started = False
    server_started = False
    try:
        scheduler.start()
        scheduler_started = True
        server_thread.start()
        server_started = True
        while not stop_event.wait(1.0):
            if not server_thread.is_alive():
                raise RuntimeError("PSK Reporter API stopped unexpectedly")
            if not scheduler.is_running():
                raise RuntimeError("PSK Reporter scheduler stopped unexpectedly")
    except (OSError, RuntimeError) as error:
        logger.error("Forge PSK Reporter service lifecycle failed: %s", error)
        return EXIT_RUNTIME_ERROR
    finally:
        if server_started:
            server.shutdown()
            server_thread.join(timeout=10.0)
        try:
            if scheduler_started:
                scheduler.stop()
        finally:
            server.close()
    logger.info("Forge PSK Reporter worker stopped")
    return EXIT_SUCCESS


def _current_snapshot(
    config: ForgePskReporterWorkerConfig,
    repository: PskReporterOrchestrationRepository,
    runtime: ForgePskReporterWorkerRuntime,
) -> ForgePskReporterWorkerSnapshot:
    latest = runtime.latest()
    now = datetime.now(UTC)
    return ForgePskReporterWorkerSnapshot(
        observed_at_utc=now,
        ingestion_enabled=config.ingestion_enabled,
        provider_enabled=config.pskreporter.enabled,
        result=None if latest is None else latest.result,
        health=repository.health(
            now_utc=now,
            enabled=config.pskreporter.enabled,
            minimum_interval=config.pskreporter.minimum_query_interval,
        ),
        runtime_error=None if latest is None else latest.runtime_error,
    )


def _print_status(path: Path) -> int:
    try:
        payload = path.read_text(encoding="utf-8")
        ForgePskReporterWorkerSnapshot.model_validate_json(payload)
    except (OSError, UnicodeError, ValidationError) as error:
        print(f"ERROR: PSK Reporter worker status is unavailable: {error}", file=sys.stderr)
        return EXIT_RUNTIME_ERROR
    print(payload, end="" if payload.endswith("\n") else "\n")
    return EXIT_SUCCESS


if __name__ == "__main__":
    raise SystemExit(main())
