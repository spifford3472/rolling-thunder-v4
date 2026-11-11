"""Explicit operator-reviewed, offline JSON import for Forge road-site evidence.

Never fetch data, trust a user-facing message as an address, or auto-import.
An operator prepares a vetted JSON file with source record IDs and timestamps.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from rolling_thunder.forge_meshcore_geo_catalog import (
    ForgeRoadSiteCatalog,
    ReviewedRoadSite,
)
from rolling_thunder.meshcore_geographic_relevance import GeoPoint

_MAX_BYTES = 250_000


def import_reviewed_file(database: Path, source: Path, *, now: datetime) -> int:
    """Read only bounded, explicitly reviewed local records, atomically import."""

    if source.is_symlink() or not source.is_file() or source.stat().st_size > _MAX_BYTES:
        raise ValueError("Unsafe or oversized import source")
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or set(payload) != {"schema", "sites"}:
        raise ValueError("Unknown import format")
    if payload["schema"] != "meshcore/road-sites-import/v1":
        raise ValueError("Unknown import schema")
    data = payload["sites"]
    if not isinstance(data, list) or not 1 <= len(data) <= 1000:
        raise ValueError("Invalid number of reviewed sites")
    sites = []
    for item in data:
        required = {
            "road",
            "exit_or_mile",
            "region",
            "latitude",
            "longitude",
            "source",
            "source_record_id",
            "observed_at",
            "reviewed_at",
            "point_specific",
        }
        if not isinstance(item, dict) or set(item) != required:
            raise ValueError("Unexpected or missing source fields")
        if type(item["point_specific"]) is not bool or not item["point_specific"]:
            raise ValueError("Not a reviewed specific site")
        for name in ("latitude", "longitude"):
            if type(item[name]) not in (float, int):
                raise ValueError("Coordinates must be numeric")
        sites.append(
            ReviewedRoadSite(
                road=item["road"],
                exit_or_mile=item["exit_or_mile"],
                region=item["region"],
                point=GeoPoint(item["latitude"], item["longitude"]),
                source=item["source"],
                source_record_id=item["source_record_id"],
                observed_at=datetime.fromisoformat(item["observed_at"]),
                reviewed_at=datetime.fromisoformat(item["reviewed_at"]),
                point_specific=True,
            )
        )
    catalog = ForgeRoadSiteCatalog(database, initialize=True)
    return catalog.import_reviewed(tuple(sites), now=now)


def main(argv: list[str] | None = None) -> int:
    """Require deliberate operator flag; do not print records or coordinates."""

    from datetime import UTC

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--reviewed-file", type=Path, required=True)
    parser.add_argument("--accept-reviewed-evidence", action="store_true")
    args = parser.parse_args(argv)
    if not args.accept_reviewed_evidence:
        parser.error("Explicit --accept-reviewed-evidence required")
    count = import_reviewed_file(args.database, args.reviewed_file, now=datetime.now(UTC))
    print(json.dumps({"schema": "meshcore/road-sites-import-result/v1", "inserted": count}))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
