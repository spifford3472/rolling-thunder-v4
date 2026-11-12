"""Read-only OHGO panel formatting, stale suppression and safe defaults."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from rolling_thunder.forge_ohgo_incidents import OhgoState
from rolling_thunder.meshcore_ohgo_panel import (
    MeshcoreOhgoPanelState,
    MeshcoreOhgoPanelWorker,
    decode_forge_ohgo,
    present_meshcore_ohgo,
)

NOW = datetime(2026, 11, 11, 22, tzinfo=UTC)


def _payload() -> dict[str, object]:
    return {
        "schema": "rolling-thunder/ohgo-incidents/v1",
        "provider": "Ohio DOT OHGO",
        "status": "current",
        "fetched_at": NOW.isoformat(),
        "driver_alert_permitted": False,
        "incidents": [
            {
                "route": "I-75",
                "location": "Near Exit 44",
                "direction": "Northbound",
                "category": "Accident",
            }
        ],
    }


def test_renders_ohgo_and_meshcore_title_without_live_fetch() -> None:
    state = decode_forge_ohgo(json.dumps(_payload()).encode(), received_at=NOW)
    view = present_meshcore_ohgo(state)
    assert "MESHCORE" in view and "OHGO" in view
    assert "I-75" in view and "Exit 44" in view
    assert "unverified for your route" in view


def test_stale_incidents_are_hidden_and_not_alerted() -> None:
    state = decode_forge_ohgo(
        json.dumps(_payload()).encode(),
        received_at=NOW + timedelta(minutes=6),
    )
    assert state.status == OhgoState.STALE
    assert "I-75" not in present_meshcore_ohgo(state)


@pytest.mark.parametrize(
    "mutation",
    [
        {"schema": "wrong"},
        {"driver_alert_permitted": True},
        {"status": "not_a_status"},
    ],
)
def test_unsupported_or_alerting_snapshot_rejected(mutation: dict[str, object]) -> None:
    payload = _payload()
    payload.update(mutation)
    with pytest.raises(ValueError):
        decode_forge_ohgo(json.dumps(payload).encode(), received_at=NOW)


def test_disabled_worker_has_no_external_fetch() -> None:
    worker = MeshcoreOhgoPanelWorker(None)
    worker.start()
    assert worker.state == MeshcoreOhgoPanelState()
    assert "not configured" in present_meshcore_ohgo(worker.state)
    worker.stop()


def test_multiple_incidents_have_visible_dividers_and_no_four_item_truncation() -> None:
    payload = _payload()
    item = payload["incidents"][0]
    assert isinstance(item, dict)
    payload["incidents"] = [{**item, "route": f"I-{n}", "location": f"Exit {n}"} for n in range(5)]
    state = decode_forge_ohgo(json.dumps(payload).encode(), received_at=NOW)
    result = present_meshcore_ohgo(state)
    assert len(state.lines) == 5
    assert result.count("──────────────") == 4
    assert "Exit 4" in result
