"""Strict non-alerting MeshCore traffic read adapter regressions."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from rolling_thunder.meshcore_incident_classification import IncidentCategory
from rolling_thunder.meshcore_public_consumer import PublicBrokerMessage
from rolling_thunder.meshcore_public_intelligence import (
    TrafficChannelSelection,
    classify_traffic_snapshot,
)

_NOW = datetime(2026, 11, 11, 20, 0, tzinfo=UTC)
_APPROVED = TrafficChannelSelection(1, "#traffic")


def _message(
    message_id: int, *, slot: int = 1,
    name: str = "#traffic", text: str = "Crash on I-75 northbound"
) -> PublicBrokerMessage:
    return PublicBrokerMessage(message_id, name, slot, text, _NOW, _NOW)


def test_only_exact_attested_channel_classified() -> None:
    messages = (
        _message(1, slot=0, name="Public"),
        _message(2, slot=5, name="#skywarn"),
        _message(3, slot=1, name="#public"),
        _message(4),
        _message(5, text="General mesh chit-chat"),
    )
    result = classify_traffic_snapshot(messages, _APPROVED)
    assert len(result) == 1
    assert result[0].broker_message_id == 4
    assert result[0].incident.category == IncidentCategory.ACCIDENT
    assert result[0].incident.road == "I-75"
    assert result[0].incident.sender == "unverified-meshcore-sender"
    assert result[0].incident.geographic_confidence == "unknown"


def test_caller_must_pin_real_approved_slot_and_name() -> None:
    with pytest.raises(ValueError):
        TrafficChannelSelection(8, "#traffic")
    with pytest.raises(ValueError):
        TrafficChannelSelection(1, "Public")
    with pytest.raises(ValueError):
        TrafficChannelSelection(True, "#traffic")
    assert classify_traffic_snapshot(
        (_message(2),), TrafficChannelSelection(2, "#traffic")
    ) == ()


def test_no_alert_or_side_effects_for_unknown_text() -> None:
    assert classify_traffic_snapshot(
        (_message(1, text="hello folks"),), _APPROVED
    ) == ()
