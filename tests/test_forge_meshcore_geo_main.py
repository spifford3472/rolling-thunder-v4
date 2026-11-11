"""No-provider, no-socket Forge catalog diagnostics."""

from __future__ import annotations

import json

from rolling_thunder.forge_meshcore_geo_catalog import ForgeRoadSiteCatalog
from rolling_thunder.forge_meshcore_geo_main import main


def test_health_and_unresolved_exact_site(tmp_path, capsys) -> None:
    path = tmp_path / "data" / "geo.db"
    ForgeRoadSiteCatalog(path, initialize=True)
    assert main(["--database", str(path), "--health"]) == 0
    health = json.loads(capsys.readouterr().out)
    assert health["records"] == 0
    assert main(["--database", str(path), "--lookup", "I-75", "44", "Ohio, USA"]) == 0
    answer = json.loads(capsys.readouterr().out)
    assert answer == {
        "schema": "meshcore/geo-lookup/v1",
        "found": False,
        "result": None,
        "incident_verified": False,
        "driver_alert_permitted": False,
    }
