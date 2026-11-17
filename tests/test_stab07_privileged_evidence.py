"""No-privilege evidence and redaction checks using fake private files."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "deploy/diagnostics/rt-stab07-readonly-evidence.py"
SPEC = importlib.util.spec_from_file_location("rt_stab07_evidence", MODULE)
assert SPEC and SPEC.loader
inspection = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inspection)


def test_hash_comparison_and_redaction(tmp_path: Path) -> None:
    wrapper = tmp_path / "root-owned-wrapper"
    snapshot = tmp_path / "snapshot"
    ft8 = tmp_path / "60-ft8-period.conf"
    wrapper.write_text("echo safe\n", encoding="utf-8")
    snapshot.write_bytes(wrapper.read_bytes())
    ft8.write_text(
        "[Service]\nEnvironment=RT_FT8_SECRET=should-not-leak\n"
        "TimeoutStopSec=20\nEnvironmentFile=/secret/private-file\n",
        encoding="utf-8",
    )
    result = inspection.collect_evidence(
        wrapper=wrapper, snapshot=snapshot, unit=None, dropins=(ft8,), root_uid=os.getuid()
    )
    assert result["installed_wrapper_matches_snapshot"] is True
    assert result["disposition"].startswith("NO_GO")
    assert result["protected_ft8_directive_names_only"] == [
        "Environment",
        "EnvironmentFile",
        "TimeoutStopSec",
    ]
    assert "should-not-leak" not in repr(result)
    assert "/secret/private-file" not in repr(result)


def test_modified_or_unreadable_files_fail_closed(tmp_path: Path) -> None:
    wrapper = tmp_path / "wrapper"
    snapshot = tmp_path / "snapshot"
    ft8 = tmp_path / "dropin"
    wrapper.write_text("old\n", encoding="utf-8")
    snapshot.write_text("new\n", encoding="utf-8")
    ft8.write_text("[Service]\n", encoding="utf-8")
    result = inspection.collect_evidence(
        wrapper=wrapper, snapshot=snapshot, unit=None, dropins=(ft8,), root_uid=os.getuid()
    )
    assert result["installed_wrapper_matches_snapshot"] is False
    wrapper.unlink()
    wrapper.symlink_to(snapshot)
    result = inspection.collect_evidence(
        wrapper=wrapper, snapshot=snapshot, unit=None, dropins=(ft8,), root_uid=os.getuid()
    )
    assert result["installed_wrapper_matches_snapshot"] is False
    assert result["installed_wrapper"]["error"] == "unsafe_file_type"


def test_all_dropins_are_hashed_without_environment_values(tmp_path: Path) -> None:
    wrapper = tmp_path / "wrapper"
    snapshot = tmp_path / "snapshot"
    unit = tmp_path / "rolling-thunder.service"
    wrapper.write_text("safe\n", encoding="utf-8")
    snapshot.write_bytes(wrapper.read_bytes())
    unit.write_text("[Service]\nTimeoutStopSec=20\n", encoding="utf-8")
    dropins = []
    for name, value in (
        ("50-ft8-evidence.conf", "Environment=FT8_SECRET=do-not-print"),
        ("60-ft8-period.conf", "EnvironmentFile=/etc/rolling-thunder/ft8-period.env"),
        ("70-ft8-attempt-delivery.conf", "EnvironmentFile=-/etc/rolling-thunder/delivery.env"),
        ("r1a-timing.conf", "Environment=RT_R1A_UI_TIMING=1"),
    ):
        path = tmp_path / name
        path.write_text(f"[Service]\n{value}\n", encoding="utf-8")
        dropins.append(path)

    result = inspection.collect_evidence(
        wrapper=wrapper,
        snapshot=snapshot,
        unit=unit,
        dropins=tuple(dropins),
        root_uid=os.getuid(),
    )

    assert result["all_protected_systemd_files_verified"] is True
    assert len(result["protected_dropins"]) == 4
    assert all(entry["state"] == "read_only_verified" for entry in result["protected_dropins"])
    assert all(entry["sha256"] for entry in result["protected_dropins"])
    assert "do-not-print" not in repr(result)
