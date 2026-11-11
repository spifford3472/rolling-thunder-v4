"""Opt-in standalone MeshCore traffic ledger worker without Tk or radio access.

Not installed as a service by default. --once processes a single bounded batch;
--loop runs a cancellable background polling worker. The only mutation outside
its isolated SQLite file is ACK of this consumer's public broker cursor, and
that happens exclusively AFTER the local SQLite transaction commits.
"""

from __future__ import annotations

import argparse
import fcntl
import logging
import os
import signal
import time
from pathlib import Path

from rolling_thunder.meshcore_public_consumer import (
    MeshcoreConsumerError,
    MeshcorePublicConsumer,
)
from rolling_thunder.meshcore_public_intelligence import TrafficChannelSelection
from rolling_thunder.meshcore_traffic_ledger import TrafficLedger, TrafficLedgerError
from rolling_thunder.meshcore_traffic_worker import MeshcoreTrafficWorker

_LOGGER = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    """Operate a single consumer identity with a local single-instance lock."""
    parser = argparse.ArgumentParser(description="Opt-in local traffic analysis worker")
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--credential", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--traffic-slot", type=int, required=True)
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--poll-seconds", type=float, default=10.0)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--loop", action="store_true")
    options = parser.parse_args(argv)
    if not 1 <= options.batch_size <= 100:
        parser.error("Batch size must be in 1-100")
    if not 2.0 <= options.poll_seconds <= 120.0:
        parser.error("Poll seconds must be in 2-120")

    # Do not create or truncate a lock in the producer database directory.
    # Local flock allows at most one independently ACKing worker identity.
    lock_path = options.database.with_suffix(options.database.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if lock_path.parent.is_symlink() or (
        lock_path.parent.stat().st_mode & 0o077
    ):
        raise TrafficLedgerError("Worker lock directory is not private")
    fd = os.open(
        lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600
    )
    try:
        if os.fstat(fd).st_mode & 0o077:
            raise TrafficLedgerError("Worker lock permissions unsafe")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise TrafficLedgerError("Traffic worker already running") from exc
        approved = TrafficChannelSelection(options.traffic_slot, "#traffic")
        ledger = TrafficLedger(options.database, approved=approved)
        client = MeshcorePublicConsumer(options.socket, options.credential)
        worker = MeshcoreTrafficWorker(client, ledger, batch_size=options.batch_size)
        if options.once:
            result = worker.run_once()
            print(
                "Traffic worker committed "
                f"{result.stored} public records, "
                f"{result.candidates} new candidates, "
                f"{result.duplicates} repeats, "
                f"{result.acknowledged} ACKs"
            )
            return 0

        stopping = False

        def stop(_signal: int, _frame: object) -> None:
            nonlocal stopping
            stopping = True

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        logging.basicConfig(level=logging.INFO)
        _LOGGER.info("Local traffic worker started, alerts/transmit disabled")
        failures = 0
        while not stopping:
            try:
                worker.run_once()
                failures = 0
            except MeshcoreConsumerError:
                # A disconnected broker or expired token must never ACK.
                failures = min(failures + 1, 6)
                _LOGGER.warning("Traffic broker unavailable; retrying after backoff")
            except (TrafficLedgerError, OSError):
                _LOGGER.error("Traffic ledger failed; worker halting without ACK")
                return 1
            wait = (
                min(120.0, options.poll_seconds * 2 ** failures)
                if failures else options.poll_seconds
            )
            end = time.monotonic() + wait
            while not stopping and time.monotonic() < end:
                time.sleep(min(0.25, max(0.0, end - time.monotonic())))
        return 0
    finally:
        os.close(fd)


if __name__ == "__main__":
    raise SystemExit(main())
