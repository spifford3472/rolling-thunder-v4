"""Explicit reviewed offline import, schema and provenance tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from rolling_thunder.forge_meshcore_geo_catalog import ForgeRoadSiteCatalog
from rolling_thunder.forge_meshcore_geo_import import import_reviewed_file
from rolling_thunder.meshcore_traffic_geocoding import TrafficGeocodeRequest

NOW = datetime(2026, 11, 11, tzinfo=UTC)


def _row() -> dict[str, object]:
    return {
        "road": "I-75",
        "exit_or_mile": "44",
        "region": "Ohio, USA",
        "latitude": 39.56,
        "longitude": -84.1,
        "source": "fake-verified-map",
        "source_record_id": "fake-site-44",
        "observed_at": (NOW - timedelta(days=1)).isoformat(),
        "reviewed_at": NOW.isoformat(),
        "point_specific": True,
    }


def test_import_requires_complete_reviewed_local_file(tmp_path) -> None:
    database = tmp_path / "catalog" / "roads.db"
    source = tmp_path / "reviewed.json"
    source.write_text(
        json.dumps(
            {
                "schema": "meshcore/road-sites-import/v1",
                "sites": [_row()],
            }
        )
    )
    assert import_reviewed_file(database, source, now=NOW) == 1
    assert import_reviewed_file(database, source, now=NOW) == 0
    catalog = ForgeRoadSiteCatalog(database)
    assert catalog.lookup(TrafficGeocodeRequest("I-75", "44", "Ohio, USA"), now=NOW) is not None


@pytest.mark.parametrize(
    "edit",
    [
        {"schema": "wrong"},
        {"sites": []},
        {"sites": [{"point_specific": False}]},
        {"sites": [{"longitude": "unknown"}]},
        {"sites": [{"road": ""}]},
    ],
)
def test_invalid_import_schema_or_reviewed_site_rejected(tmp_path, edit) -> None:
    payload: dict[str, object] = {
        "schema": "meshcore/road-sites-import/v1",
        "sites": [_row()],
    }
    if "sites" in edit and edit["sites"] == []:
        payload["sites"] = []
    elif "sites" in edit:
        row = _row()
        row.update(edit["sites"][0])
        payload["sites"] = [row]
    else:
        payload.update(edit)
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(payload))
    with pytest.raises((ValueError, TypeError)):
        import_reviewed_file(tmp_path / "catalog.db", path, now=NOW)
