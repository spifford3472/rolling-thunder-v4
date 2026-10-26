"""Independent HTTPS NOAA publisher; never makes VOACAP requests or changes gates."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from rolling_thunder.forge_solar_ssn import NoaaSwpcPredictedSsnAdapter, UrllibSsnFeedTransport
from rolling_thunder.forge_voacap_baseline import BaselinePlan, EnvironmentSnapshot


def build_environment(
    plan: BaselinePlan, *, now: datetime, forecast_day: Literal["current", "next"] = "next"
) -> tuple[str, str]:
    """Return verified paired JSON artifacts; caller controls publishing."""
    if now.tzinfo is None:
        raise ValueError("clock must be timezone aware")
    if forecast_day not in ("current", "next"):
        raise ValueError("forecast_day must be current or next")
    target_day = now.astimezone(UTC).date() + timedelta(days=forecast_day == "next")
    month = f"{target_day.year:04d}-{target_day.month:02d}"
    snapshot = NoaaSwpcPredictedSsnAdapter(
        transport=UrllibSsnFeedTransport(), timeout_s=10.0
    ).fetch(target_month=month)
    # A real HTTPS capture occurs after the caller chooses its target month.
    # Validate the returned evidence against its actual capture timestamp;
    # the sampler separately rejects stale or future-dated artifacts.
    if (
        snapshot.source_id != plan.ssn_source
        or snapshot.source_version != plan.ssn_source_version
        or snapshot.source_schema != plan.ssn_source_schema
        or snapshot.source_revision_policy != plan.ssn_revision_policy
    ):
        raise ValueError("NOAA source identity does not match immutable operational plan")
    environment = EnvironmentSnapshot(
        ssn=snapshot.value,
        value_semantics="monthly_smoothed_predicted_sunspot_number",
        target_month=snapshot.target_month,
        source=snapshot.source_id,
        source_url=snapshot.source_url,
        source_version=snapshot.source_version,
        source_schema=snapshot.source_schema,
        source_revision_policy=snapshot.source_revision_policy,
        source_record_id=snapshot.source_record_id,
        source_released_at_utc=snapshot.source_released_at_utc,
        captured_at_utc=snapshot.captured_at_utc,
        raw_sha256=snapshot.raw_sha256,
        snapshot_canonical_sha256=snapshot.canonical_sha256,
    )
    return (snapshot.model_dump_json(indent=2) + "\n",
            environment.model_dump_json(indent=2) + "\n")


def _atomic_publish(path: Path, content: str) -> None:
    # Each file is atomic. Reader cross-checks snapshot and environment hashes
    # and fails closed if caught between publishes.
    fd, tmp = tempfile.mkstemp(prefix=".noaa-refresh-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh C6 NOAA artifacts without VOACAP POSTs")
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--snapshot-output", required=True, type=Path)
    parser.add_argument("--environment-output", required=True, type=Path)
    parser.add_argument("--forecast-day", choices=("current", "next"), default="next",
                        help="current UTC day for scheduled capture; next day for legacy slots")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    plan = BaselinePlan.model_validate_json(args.plan.read_text())
    snapshot, environment = build_environment(plan, now=datetime.now(UTC), forecast_day=args.forecast_day)
    if args.apply:
        if args.snapshot_output.parent != args.environment_output.parent:
            parser.error("NOAA snapshot/environment must share a reviewed destination directory")
        _atomic_publish(args.snapshot_output, snapshot)
        _atomic_publish(args.environment_output, environment)
    print(json.dumps({"state": "applied" if args.apply else "dry_run",
                      "plan_id": str(plan.plan_id), "provider_calls": 0}))


if __name__ == "__main__":
    main()
