"""Produce a bounded, payload-free report from exported issue #345 timing text."""

from __future__ import annotations

import argparse
import json
import math
import re
import stat
from collections.abc import Sequence
from pathlib import Path

MAX_INPUT_BYTES = 8 * 1024 * 1024
MAX_LINES = 100_000
MAX_LINE_BYTES = 64 * 1024
MAX_RECOGNIZED_RECORDS = 4096
MAX_COUNT = 1_000_000
MAX_DURATION_MS = 86_400_000.0

SCENARIOS = ("radar_off", "radar_on", "forge_slow", "unlabeled")
METRIC_NAMES = frozenset({"refresh", "controls", "map", "base_map", "radar", "refresh_gap"})
PHASE_NAMES = (
    "pre_controls",
    "controls",
    "map_prepare",
    "map_update",
    "presentation",
    "context_widgets",
)
SUBPHASE_NAMES = frozenset(
    {
        "radio_sync",
        "spot_tune_status",
        "repeater_persistence",
        "dmr_commits",
        "weather_update",
        "weather_alert_update",
        "weather_alert_viewport",
        "gps_snapshot",
        "map_controller",
        "map_viewport_request",
        "map_snapshot",
        "pota_viewport_request",
        "radar_viewport_request",
        "ft8_panel_snapshot",
        "ft8_receive_target",
        "ft8_receive_snapshot",
        "ft8_presentation",
        "base_plan",
        "base_b64",
        "base_photo",
        "base_canvas",
        "pota_canvas",
        "radar_plan",
        "radar_b64",
        "radar_photo",
        "radar_canvas",
        "overlay_status_canvas",
    }
)
ACTION_NAMES = frozenset(
    {
        "voice",
        "commit",
        "discard",
        "next_context",
        "home_context",
        "select_pota",
        "select_dx",
        "select_repeaters",
        "select_ai",
        "select_settings",
        "panel_primary",
        "panel_secondary",
        "panel_tertiary",
        "panel_tertiary_long",
        "move_previous",
        "move_next",
        "activate_selection",
        "back",
    }
)

_NUMBER = r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?"
_AGGREGATE_RE = re.compile(
    rf"R1A_UI_TIMING metric=(?P<metric>[a-z_]+) "
    rf"count=(?P<count>[0-9]+) p95_ms=(?P<p95>{_NUMBER}) "
    rf"max_ms=(?P<maximum>{_NUMBER})"
)
_SLOW_RE = re.compile(
    rf"R1C2_SLOW_REFRESH id=(?P<refresh_id>[0-9]+) "
    rf"duration_ms=(?P<duration>{_NUMBER}) "
    + " ".join(rf"{name}_ms=(?P<{name}>{_NUMBER})" for name in PHASE_NAMES)
    + r"(?: subphases=(?P<subphases>[^ ]+) actions=(?P<actions>[^ ]+))?"
)
_DETAIL_RE = re.compile(
    rf"(?P<name>[a-z0-9_]+):(?P<count>[0-9]+):"
    rf"(?P<total>{_NUMBER}):(?P<maximum>{_NUMBER})"
)
_SHA_RE = re.compile(r"[0-9a-fA-F]{40}")


def _bounded_count(value: str) -> int | None:
    parsed = int(value)
    return parsed if 0 <= parsed <= MAX_COUNT else None


def _bounded_duration(value: str) -> float | None:
    parsed = float(value)
    if not math.isfinite(parsed) or not 0.0 <= parsed <= MAX_DURATION_MS:
        return None
    return parsed


def _parse_details(
    raw: str | None, allowed_names: frozenset[str]
) -> dict[str, dict[str, int | float]] | None:
    if raw is None or raw == "none":
        return {}
    parsed: dict[str, dict[str, int | float]] = {}
    for item in raw.split(","):
        match = _DETAIL_RE.fullmatch(item)
        if match is None or match["name"] not in allowed_names:
            return None
        name = match["name"]
        count = _bounded_count(match["count"])
        total = _bounded_duration(match["total"])
        maximum = _bounded_duration(match["maximum"])
        if (
            name in parsed
            or count is None
            or count < 1
            or total is None
            or maximum is None
            or maximum > total
        ):
            return None
        parsed[name] = {"count": count, "total_ms": total, "max_ms": maximum}
    return parsed


def _update_aggregate(
    aggregates: dict[str, dict[str, int | float]],
    metric: str,
    count: int,
    p95_ms: float,
    maximum_ms: float,
) -> None:
    current = aggregates.get(metric)
    if current is None:
        aggregates[metric] = {
            "window_record_count": 1,
            "sample_count_min": count,
            "sample_count_max": count,
            "reported_p95_ms_min": p95_ms,
            "reported_p95_ms_max": p95_ms,
            "reported_max_ms_min": maximum_ms,
            "reported_max_ms_max": maximum_ms,
        }
        return
    current["window_record_count"] = int(current["window_record_count"]) + 1
    current["sample_count_min"] = min(int(current["sample_count_min"]), count)
    current["sample_count_max"] = max(int(current["sample_count_max"]), count)
    current["reported_p95_ms_min"] = min(float(current["reported_p95_ms_min"]), p95_ms)
    current["reported_p95_ms_max"] = max(float(current["reported_p95_ms_max"]), p95_ms)
    current["reported_max_ms_min"] = min(float(current["reported_max_ms_min"]), maximum_ms)
    current["reported_max_ms_max"] = max(float(current["reported_max_ms_max"]), maximum_ms)


def parse_timing_file(input_path: Path) -> dict[str, object]:
    """Parse only fixed timing records from one bounded regular text file."""
    file_stat = input_path.stat()
    if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_size > MAX_INPUT_BYTES:
        raise ValueError("input must be a bounded regular file")

    aggregates: dict[str, dict[str, int | float]] = {}
    slow_refreshes: list[dict[str, object]] = []
    line_count = 0
    byte_count = 0
    recognized_count = 0
    ignored_count = 0

    with input_path.open("rb") as source:
        for raw_line in source:
            line_count += 1
            byte_count += len(raw_line)
            if (
                byte_count > MAX_INPUT_BYTES
                or line_count > MAX_LINES
                or len(raw_line) > MAX_LINE_BYTES
            ):
                raise ValueError("input exceeds parser bounds")
            try:
                line = raw_line.rstrip(b"\r\n").decode("ascii")
            except UnicodeDecodeError:
                ignored_count += 1
                continue

            aggregate_match = _AGGREGATE_RE.fullmatch(line)
            if aggregate_match is not None and aggregate_match["metric"] in METRIC_NAMES:
                count = _bounded_count(aggregate_match["count"])
                p95_ms = _bounded_duration(aggregate_match["p95"])
                maximum_ms = _bounded_duration(aggregate_match["maximum"])
                if (
                    count is not None
                    and count >= 1
                    and p95_ms is not None
                    and maximum_ms is not None
                    and p95_ms <= maximum_ms
                ):
                    _update_aggregate(
                        aggregates,
                        aggregate_match["metric"],
                        count,
                        p95_ms,
                        maximum_ms,
                    )
                    recognized_count += 1
                    if recognized_count > MAX_RECOGNIZED_RECORDS:
                        raise ValueError("input contains too many timing records")
                    continue

            slow_match = _SLOW_RE.fullmatch(line)
            if slow_match is not None:
                refresh_id = _bounded_count(slow_match["refresh_id"])
                duration_ms = _bounded_duration(slow_match["duration"])
                phases = {name: _bounded_duration(slow_match[name]) for name in PHASE_NAMES}
                subphases = _parse_details(slow_match["subphases"], SUBPHASE_NAMES)
                actions = _parse_details(slow_match["actions"], ACTION_NAMES)
                if (
                    refresh_id is not None
                    and duration_ms is not None
                    and all(value is not None for value in phases.values())
                    and subphases is not None
                    and actions is not None
                ):
                    slow_refreshes.append(
                        {
                            "refresh_id": refresh_id,
                            "duration_ms": duration_ms,
                            "phases_ms": phases,
                            "subphases": subphases,
                            "actions": actions,
                        }
                    )
                    recognized_count += 1
                    if recognized_count > MAX_RECOGNIZED_RECORDS:
                        raise ValueError("input contains too many timing records")
                    continue
            ignored_count += 1

    return {
        "line_count": line_count,
        "recognized_record_count": recognized_count,
        "ignored_line_count": ignored_count,
        "aggregate_windows": dict(sorted(aggregates.items())),
        "slow_refresh_records": slow_refreshes,
    }


def build_report(input_path: Path, scenario: str, source_sha: str) -> dict[str, object]:
    """Bind parsed records to operator-declared provenance without inferring state."""
    if scenario not in SCENARIOS:
        raise ValueError("unsupported scenario")
    if _SHA_RE.fullmatch(source_sha) is None:
        raise ValueError("source SHA must contain exactly 40 hexadecimal characters")
    return {
        "scenario": scenario,
        "source_sha": source_sha.lower(),
        "acceptance_complete": False,
        "global_percentiles_available": False,
        "operator_end_to_end_latency_available": False,
        "slow_refresh_sample_complete": False,
        **parse_timing_file(input_path),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report exported issue #345 timings")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--scenario", choices=SCENARIOS, default="unlabeled")
    parser.add_argument("--source-sha", required=True)
    args = parser.parse_args(argv)
    try:
        report = build_report(args.input, args.scenario, args.source_sha)
    except OSError:
        parser.error("input could not be read")
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
