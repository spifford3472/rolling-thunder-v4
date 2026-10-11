"""Fake-only CLI for audited offline FT8 historical replay."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from rolling_thunder.forge_ft8_historical_replay import (
    load_fake_voacap_fixture,
    run_audited_historical_replay,
)

EXIT_SUCCESS = 0
EXIT_USAGE = 2
EXIT_REPLAY_FAILED = 3
_COPY_ACKNOWLEDGEMENT = "copied-fixture-only"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rolling-thunder-forge-ft8-historical-replay",
        description=(
            "Offline audited replay into a new SQLite history copy using only a "
            "deterministic local fake-provider fixture"
        ),
    )
    parser.add_argument("--source-inbox", type=Path, required=True)
    parser.add_argument("--source-history", type=Path, required=True)
    parser.add_argument("--replay-history-output", type=Path, required=True)
    parser.add_argument("--report-output", type=Path, required=True)
    parser.add_argument("--fake-provider-fixture", type=Path, required=True)
    parser.add_argument("--release-identifier", required=True)
    parser.add_argument(
        "--replayed-at-utc",
        type=datetime.fromisoformat,
        required=True,
        help="Explicit timezone-aware audit timestamp; no wall clock is consulted",
    )
    parser.add_argument(
        "--copied-fixture-acknowledgement",
        required=True,
        choices=(_COPY_ACKNOWLEDGEMENT,),
        help="Must be exactly 'copied-fixture-only'; production paths are prohibited",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report_path = args.report_output.resolve()
    if report_path.exists():
        print(f"ERROR: report output already exists: {report_path}", file=sys.stderr)
        return EXIT_USAGE
    if not report_path.parent.is_dir():
        print(
            f"ERROR: report output parent does not exist: {report_path.parent}",
            file=sys.stderr,
        )
        return EXIT_USAGE
    try:
        fixture = load_fake_voacap_fixture(args.fake_provider_fixture)
        report = run_audited_historical_replay(
            args.source_inbox,
            args.source_history,
            args.replay_history_output,
            fixture,
            replayed_at_utc=args.replayed_at_utc,
            release_identifier=args.release_identifier,
        )
        with report_path.open("x", encoding="utf-8") as output:
            output.write(report.model_dump_json(indent=2) + "\n")
    except (
        FileExistsError,
        FileNotFoundError,
        OSError,
        RuntimeError,
        ValueError,
        ValidationError,
        sqlite3.Error,
    ) as error:
        print(f"ERROR: historical replay failed: {error}", file=sys.stderr)
        return EXIT_REPLAY_FAILED
    print(report.model_dump_json())
    return EXIT_SUCCESS


if __name__ == "__main__":
    raise SystemExit(main())
