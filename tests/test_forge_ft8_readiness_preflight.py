import sqlite3
from pathlib import Path

from rolling_thunder.forge_ft8_readiness_preflight import REQUIRED, inspect_sources


def test_missing_paths_fail_closed(tmp_path: Path) -> None:
    response = inspect_sources({name: tmp_path / name for name in REQUIRED})
    assert not response["preflight_passed"]
    assert all(not value["valid"] for value in response["sources"].values())
    assert response["provider_egress_performed"] is False
    assert response["radio_control_performed"] is False


def test_schema_checked_without_modifying_source_bytes(tmp_path: Path) -> None:
    paths: dict[str, Path] = {}
    before: dict[str, bytes] = {}
    for name, tables in REQUIRED.items():
        path = tmp_path / f"{name}.db"
        with sqlite3.connect(path) as db:
            for table in tables:
                db.execute(f"CREATE TABLE {table} (id TEXT)")
        paths[name] = path
        before[name] = path.read_bytes()
    output = inspect_sources(paths)
    assert output["preflight_passed"]
    assert all(paths[k].read_bytes() == before[k] for k in REQUIRED)


def test_missing_schema_disqualifies_source(tmp_path: Path) -> None:
    paths = {name: tmp_path / f"{name}.db" for name in REQUIRED}
    for path in paths.values():
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE unrelated (id INT)")
    assert not inspect_sources(paths)["preflight_passed"]
