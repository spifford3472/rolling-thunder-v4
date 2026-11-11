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

_UNVERIFIED_SENDER = "unverified-meshcore-sender"


@dataclass(frozen=True, slots=True)
class TrafficChannelSelection:
    """Explicit operator-approved public slot; not inferred from channel text."""

    slot: int
    name: str

    def __post_init__(self) -> None:
        if type(self.slot) is not int or not 0 <= self.slot < 8:
            raise ValueError("Invalid approved traffic slot")
        if self.name != "#traffic":
            raise ValueError("Only the explicitly approved #traffic channel is supported")


@dataclass(frozen=True, slots=True)
class TrafficCandidate:
    """Potential event, with source message ID and no delivery side effects."""

    broker_message_id: int
    incident: ClassifiedIncident


def classify_traffic_snapshot(
    messages: tuple[PublicBrokerMessage, ...],
    approved: TrafficChannelSelection,
) -> tuple[TrafficCandidate, ...]:
    """Never interpret generic Public messages or other slots as #traffic.

    The underlying classifier is only applied to the exact broker-attested
    #traffic slot and channel label. Unknown/unmatched text is not an alert.
    """
    channel_id = f"{approved.slot}:{approved.name}"
    policy = PublicChannelPolicy(
        traffic_ids=frozenset({channel_id}),
        skywarn_ids=frozenset({"skywarn-not-enabled"}),
    )
    candidates: list[TrafficCandidate] = []
    for message in messages:
        if message.channel_slot != approved.slot or message.channel_name != approved.name:
            continue
        classified = classify_public_message(
            PublicMessage(
                channel_id=channel_id,
                sender=_UNVERIFIED_SENDER,
                text=message.text,
                received_at=message.received_at,
            ),
            policy,
        )
        if classified is not None and classified.category != IncidentCategory.UNKNOWN:
            candidates.append(TrafficCandidate(message.message_id, classified))
    return tuple(candidates)
