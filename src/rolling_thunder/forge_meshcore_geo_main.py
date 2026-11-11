"""Operator-run, read-only Forge road-site catalog inspection.

This CLI never imports map data, opens a port, contacts a map provider, starts
a service, or runs in the dashboard. Catalog initialization/import is a
distinct reviewed offline administration operation.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from rolling_thunder.forge_meshcore_geo_catalog import ForgeRoadSiteCatalog
from rolling_thunder.meshcore_traffic_geocoding import TrafficGeocodeRequest


def main(argv: list[str] | None = None) -> int:
    """Return a bounded, versioned JSON health or exact lookup snapshot."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--health", action="store_true")
    group.add_argument("--lookup", nargs=3, metavar=("ROAD", "EXIT_OR_MILE", "REGION"))
    args = parser.parse_args(argv)
    catalog = ForgeRoadSiteCatalog(args.database)
    if args.health:
        response: dict[str, object] = dict(catalog.health())
    else:
        road, landmark, region = args.lookup
        record = catalog.lookup(
            TrafficGeocodeRequest(road, landmark, region),
            now=datetime.now(UTC),
        )
        response = {
            "schema": "meshcore/geo-lookup/v1",
            "found": record is not None,
            "result": (
                {
                    "latitude": record.latitude,
                    "longitude": record.longitude,
                    "road": record.road,
                    "exit_or_mile": record.exit_or_mile,
                    "source": record.source,
                    "point_specific": record.point_specific,
                    "route_alignment_verified": record.route_alignment_verified,
                }
                if record is not None
                else None
            ),
            "incident_verified": False,
            "driver_alert_permitted": False,
        }
    print(json.dumps(response, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
