"""Read-only bridge from verified broker public text to incident candidates.

A channel name alone is insufficient evidence; the broker must have attested
the configured slot/key before delivering public content. A sender is NOT
authenticated by MeshCore channel text, so reports remain unverified. No
automatic notifications, geocoding, acknowledgement, navigation or RF actions.
"""

from __future__ import annotations

from dataclasses import dataclass

from rolling_thunder.meshcore_incident_classification import (
    ClassifiedIncident,
    IncidentCategory,
    PublicChannelPolicy,
    PublicMessage,
    classify_public_message,
)
from rolling_thunder.meshcore_public_consumer import PublicBrokerMessage

_TRAFFIC_SLOT = 1
_TRAFFIC_NAME = "#traffic"
_TRAFFIC_ID = "1:#traffic"
_SKYWARN_ID = "5:#skywarn"
_UNVERIFIED_SENDER = "unverified-meshcore-sender"
_POLICY = PublicChannelPolicy(
    traffic_ids=frozenset({_TRAFFIC_ID}),
    skywarn_ids=frozenset({_SKYWARN_ID}),
)


@dataclass(frozen=True, slots=True)
class TrafficCandidate:
    """Potential event, with source message ID and no delivery side effects."""

    broker_message_id: int
    incident: ClassifiedIncident


def classify_traffic_snapshot(
    messages: tuple[PublicBrokerMessage, ...],
) -> tuple[TrafficCandidate, ...]:
    """Never interpret generic Public messages or other slots as #traffic.

    The underlying classifier is only applied to the exact broker-attested
    #traffic slot and channel label. Unknown/unmatched text is not an alert.
    """
    candidates: list[TrafficCandidate] = []
    for message in messages:
        if message.channel_slot != _TRAFFIC_SLOT or message.channel_name != _TRAFFIC_NAME:
            continue
        classified = classify_public_message(
            PublicMessage(
                channel_id=_TRAFFIC_ID,
                sender=_UNVERIFIED_SENDER,
                text=message.text,
                received_at=message.received_at,
            ),
            _POLICY,
        )
        if classified is not None and classified.category != IncidentCategory.UNKNOWN:
            candidates.append(TrafficCandidate(message.message_id, classified))
    return tuple(candidates)
