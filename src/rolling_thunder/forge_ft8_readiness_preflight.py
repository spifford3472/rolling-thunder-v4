"""Non-privileged, read-only Forge readiness commissioning preflight."""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from urllib.parse import quote

REQUIRED: dict[str, tuple[str, ...]] = {
    "inbox": ("ft8_attempt_inbox",),
    "history": ("ft8_attempt_provenance_v1", "voacap_attempt_link_v1", "voacap_prediction_run_v1", "voacap_prediction_input_v1"),
    "c4": ("baseline_slot_v1", "baseline_provider_response_v1", "baseline_plan_v1"),
}


def inspect_sources(paths: dict[str, Path]) -> dict[str, object]:
    sources: dict[str, dict[str, object]] = {}
    passed = True
    for name, required in REQUIRED.items():
        path = paths[name]
        report: dict[str, object] = {"path": str(path), "read_only": True, "valid": False}
        if not path.is_file():
            report["reason"] = "source_file_missing"
            passed = False
            sources[name] = report
            continue
        try:
            uri = "file:" + quote(str(path.resolve()), safe="/") + "?mode=ro"
            with sqlite3.connect(uri, uri=True, timeout=2) as db:
                db.execute("PRAGMA query_only=ON")
                result = db.execute("PRAGMA quick_check").fetchone()
                tables = {str(row[0]) for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )}
                missing = sorted(set(required) - tables)
                report["sqlite_quick_check"] = result[0] if result else None
                report["missing_tables"] = missing
                report["valid"] = not missing and result == ("ok",)
                if not report["valid"]:
                    report["reason"] = "schema_or_integrity_invalid"
                    passed = False
        except (sqlite3.Error, OSError):
            report["reason"] = "sqlite_read_only_access_failed"
            passed = False
        sources[name] = report
    return {"schema_version": 1, "preflight_passed": passed, "sources": sources,
            "provider_egress_performed": False, "radio_control_performed": False}


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only Forge FT8 readiness source preflight")
    for key in REQUIRED:
        parser.add_argument(f"--{key}-db", required=True, type=Path)
    args = parser.parse_args()
    output = inspect_sources({key: getattr(args, f"{key}_db") for key in REQUIRED})
    print(json.dumps(output, sort_keys=True))
    if not output["preflight_passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
