"""Tests for the bounded offline issue #345 timing reporter."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "issue345_timing_report.py"
SPEC = importlib.util.spec_from_file_location("issue345_timing_report", TOOL_PATH)
assert SPEC is not None and SPEC.loader is not None
timing_report = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(timing_report)

SHA = "d271d065e5ee75282f326a50016648eed8f88f03"


def test_report_keeps_windows_separate_from_same_refresh_slow_detail(tmp_path: Path) -> None:
    timing_input = tmp_path / "timing.txt"
    timing_input.write_text(
        """R1A_UI_TIMING metric=refresh count=240 p95_ms=35.93 max_ms=167.33
R1A_UI_TIMING metric=refresh count=256 p95_ms=27.48 max_ms=174.20
R1C2_SLOW_REFRESH id=397 duration_ms=174.20 pre_controls_ms=0.26 controls_ms=0.15 map_prepare_ms=6.26 map_update_ms=121.17 presentation_ms=42.46 context_widgets_ms=3.90 subphases=base_plan:1:0.01:0.01,ft8_receive_target:1:0.18:0.18,overlay_status_canvas:1:115.79:115.79 actions=move_next:2:20.00:12.50""",
        encoding="ascii",
    )

    report = timing_report.build_report(timing_input, "unlabeled", SHA)

    assert report["global_percentiles_available"] is False
    assert report["slow_refresh_sample_complete"] is False
    refresh = report["aggregate_windows"]["refresh"]
    assert refresh == {
        "window_record_count": 2,
        "sample_count_min": 240,
        "sample_count_max": 256,
        "reported_p95_ms_min": 27.48,
        "reported_p95_ms_max": 35.93,
        "reported_max_ms_min": 167.33,
        "reported_max_ms_max": 174.2,
    }
    slow = report["slow_refresh_records"][0]
    assert slow["refresh_id"] == 397
    assert slow["phases_ms"]["map_update"] == 121.17
    assert slow["subphases"]["overlay_status_canvas"]["max_ms"] == 115.79
    assert slow["subphases"]["ft8_receive_target"]["max_ms"] == 0.18
    assert slow["actions"]["move_next"] == {
        "count": 2,
        "total_ms": 20.0,
        "max_ms": 12.5,
    }


def test_unknown_and_malformed_content_is_counted_but_never_copied(tmp_path: Path) -> None:
    timing_input = tmp_path / "timing.txt"
    secret = "K1ABC arbitrary payload"
    timing_input.write_text(
        f"""{secret}
R1A_UI_TIMING metric=unknown count=256 p95_ms=1.00 max_ms=2.00
R1A_UI_TIMING metric=refresh count=256 p95_ms=9.00 max_ms=8.00
R1C2_SLOW_REFRESH id=1 duration_ms=101.00 pre_controls_ms=1.00 controls_ms=1.00 map_prepare_ms=1.00 map_update_ms=1.00 presentation_ms=1.00 context_widgets_ms=1.00 subphases=callsign_k1abc:1:1.00:1.00 actions=none""",
        encoding="ascii",
    )

    report = timing_report.build_report(timing_input, "unlabeled", SHA)
    encoded = json.dumps(report)

    assert report["recognized_record_count"] == 0
    assert report["ignored_line_count"] == 4
    assert secret not in encoded
    assert "callsign_k1abc" not in encoded
    assert report["aggregate_windows"] == {}
    assert report["slow_refresh_records"] == []


def test_legacy_slow_record_does_not_invent_missing_probe_detail(tmp_path: Path) -> None:
    timing_input = tmp_path / "timing.txt"
    timing_input.write_text(
        "R1C2_SLOW_REFRESH id=838146 duration_ms=148.65 "
        "pre_controls_ms=0.21 controls_ms=0.14 map_prepare_ms=4.34 "
        "map_update_ms=50.53 presentation_ms=80.07 context_widgets_ms=13.35\n",
        encoding="ascii",
    )

    report = timing_report.build_report(timing_input, "unlabeled", SHA)
    slow = report["slow_refresh_records"][0]

    assert slow["subphases"] == {}
    assert slow["actions"] == {}
    assert slow["phases_ms"]["presentation"] == 80.07


def test_parser_rejects_oversize_input_and_invalid_provenance(tmp_path: Path) -> None:
    timing_input = tmp_path / "timing.txt"
    timing_input.write_bytes(b"x" * (timing_report.MAX_INPUT_BYTES + 1))

    with pytest.raises(ValueError, match="bounded regular file"):
        timing_report.build_report(timing_input, "unlabeled", SHA)
    with pytest.raises(ValueError, match="unsupported scenario"):
        timing_report.build_report(tmp_path / "missing", "guessed", SHA)
    with pytest.raises(ValueError, match="exactly 40"):
        timing_report.build_report(tmp_path / "missing", "unlabeled", "d271d06")


def test_cli_defaults_to_unlabeled_and_prints_bounded_json(tmp_path: Path) -> None:
    timing_input = tmp_path / "timing.txt"
    timing_input.write_text(
        "R1A_UI_TIMING metric=radar count=256 p95_ms=0.03 max_ms=0.09\n",
        encoding="ascii",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(TOOL_PATH),
            "--input",
            str(timing_input),
            "--source-sha",
            SHA,
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(completed.stdout)

    assert completed.stderr == ""
    assert report["scenario"] == "unlabeled"
    assert report["source_sha"] == SHA
    assert set(report["aggregate_windows"]) == {"radar"}
