"""Import a validated POTA park CSV into Rolling Thunder's offline catalog."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rolling_thunder.pota_catalog import PotaCatalogImportError, import_pota_catalog_csv


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rolling-thunder-pota-catalog",
        description="Validate and atomically replace the offline POTA park catalog.",
    )
    parser.add_argument("source", type=Path, help="POTA park CSV file")
    parser.add_argument(
        "--database",
        type=Path,
        default=Path("data/pota/pota-catalog.db"),
        help="catalog database path (default: data/pota/pota-catalog.db)",
    )
    parser.add_argument(
        "--source-version",
        help="optional source date/version label stored with the catalog",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = import_pota_catalog_csv(
            args.source,
            args.database,
            source_version=args.source_version,
        )
    except PotaCatalogImportError as error:
        print(f"POTA catalog import rejected: {error}", file=sys.stderr)
        return 2

    print(
        "POTA catalog imported: "
        f"parks={result.park_count} "
        f"database={result.database_path} "
        f"sha256={result.source_sha256}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
