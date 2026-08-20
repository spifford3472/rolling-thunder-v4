"""Tests for Log-panel timestamp presentation."""

from datetime import UTC, datetime

from rolling_thunder.log_ui import format_log_timestamp


def test_log_timestamp_displays_authoritative_date_and_time() -> None:
    started_at = datetime(2026, 8, 19, 20, 23, 45, tzinfo=UTC)

    rendered = format_log_timestamp(started_at)

    assert rendered == "08/19/26 20:23Z"
    assert "08/19/26" in rendered
    assert "20:23" in rendered
