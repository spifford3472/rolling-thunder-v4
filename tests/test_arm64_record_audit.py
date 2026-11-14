"""Offline ARM64 installed RECORD verification using disposable fake packages."""

from __future__ import annotations

import base64
import csv
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "deploy/rolling-thunder-arm64-record-audit.py"
SPEC = importlib.util.spec_from_file_location("rt_arm64_record_audit", SOURCE)
assert SPEC and SPEC.loader
record = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(record)


def _digest(data: bytes) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode("ascii")


def _package(site: Path, name: str, version: str) -> None:
    """Create a self-consistent wheel RECORD without installing packages."""
    dist = site / f"{name.replace('-', '_')}-{version}.dist-info"
    dist.mkdir()
    data = f"# {name} fixture\n".encode()
    file = site / (name.replace("-", "_") + ".py")
    file.write_bytes(data)
    metadata = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n".encode()
    (dist / "METADATA").write_bytes(metadata)
    rows = [
        (file.name, "sha256=" + _digest(data), str(len(data))),
        (dist.name + "/METADATA", "sha256=" + _digest(metadata), str(len(metadata))),
        (dist.name + "/RECORD", "", ""),
    ]
    with (dist / "RECORD").open("w", encoding="utf-8", newline="") as stream:
        csv.writer(stream).writerows(rows)


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    venv = tmp_path / "venv"
    site = venv / "lib/python3.13/site-packages"
    site.mkdir(parents=True)
    pins = {}
    for n in range(26):
        package = f"package{n:02}"
        pins[package] = {"version": "1.0"}
        _package(site, package, "1.0")
    _package(site, "rolling-thunder", "4.4.1")
    (site / "pip-25.1.1.dist-info").mkdir()
    (site / "pip-25.1.1.dist-info/METADATA").write_text(
        "Name: pip\nVersion: 25.1.1\n", encoding="utf-8"
    )
    lock = tmp_path / "lock.json"
    lock.write_text(json.dumps({"packages": pins}), encoding="utf-8")
    return venv, lock


def test_complete_record_inventory_stays_nonproduction(tmp_path: Path) -> None:
    venv, lock = _fixture(tmp_path)
    result = record.audit(venv, lock, app_name="rolling-thunder", app_version="4.4.1")
    assert result["dependencies_checked"] == 26
    assert result["hashes_verified"] == 54
    assert result["record_entries_checked"] == 81
    assert result["debian_pip_bootstrap_separately_managed"] is True
    assert result["production_ready"] is False


def test_modified_installed_payload_is_detected(tmp_path: Path) -> None:
    venv, lock = _fixture(tmp_path)
    path = venv / "lib/python3.13/site-packages/package01.py"
    path.write_bytes(b"changed code")
    with pytest.raises(record.RecordAuditError, match="content mismatch"):
        record.audit(venv, lock, app_name="rolling-thunder", app_version="4.4.1")


def test_missing_dependency_and_unknown_distribution_fail_closed(tmp_path: Path) -> None:
    venv, lock = _fixture(tmp_path)
    site = venv / "lib/python3.13/site-packages"
    (site / "package01-1.0.dist-info").rename(site / "package01-1.0.removed")
    with pytest.raises(record.RecordAuditError, match="missing installed dependency"):
        record.audit(venv, lock, app_name="rolling-thunder", app_version="4.4.1")
    _package(site, "intruder", "1.0")
    with pytest.raises(record.RecordAuditError, match="unexpected"):
        record.audit(venv, lock, app_name="rolling-thunder", app_version="4.4.1")


def test_unhashed_payload_refused(tmp_path: Path) -> None:
    venv, lock = _fixture(tmp_path)
    path = venv / "lib/python3.13/site-packages/package01-1.0.dist-info/RECORD"
    lines = path.read_text().splitlines()
    lines[0] = "package01.py,,"
    path.write_text("\n".join(lines) + "\n")
    with pytest.raises(record.RecordAuditError, match="unhashed"):
        record.audit(venv, lock, app_name="rolling-thunder", app_version="4.4.1")


def test_installed_symlink_cannot_bypass_record(tmp_path: Path) -> None:
    venv, lock = _fixture(tmp_path)
    site = venv / "lib/python3.13/site-packages"
    victim = site / "package01.py"
    target = site / "package01-original.py"
    victim.rename(target)
    victim.symlink_to(target)
    with pytest.raises(record.RecordAuditError, match="symlinked"):
        record.audit(venv, lock, app_name="rolling-thunder", app_version="4.4.1")


def test_record_traversal_outside_private_venv_refused(tmp_path: Path) -> None:
    venv, lock = _fixture(tmp_path)
    dist = venv / "lib/python3.13/site-packages/package01-1.0.dist-info"
    record_path = dist / "RECORD"
    with record_path.open("a", encoding="utf-8") as stream:
        stream.write("../../../../../../../../etc/passwd,sha256=not-valid,\n")
    with pytest.raises(record.RecordAuditError, match="escaped"):
        record.audit(venv, lock, app_name="rolling-thunder", app_version="4.4.1")
