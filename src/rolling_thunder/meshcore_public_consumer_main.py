"""Operator-safe read-only MeshCore public message preview on local Unix socket.

This diagnostic does not acknowledge/consume broker messages, subscribe to
alerts, send over RF, open raw serial, or access any private stream.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rolling_thunder.meshcore_public_consumer import (
    MeshcoreConsumerError,
    MeshcorePublicConsumer,
)
from rolling_thunder.meshcore_public_intelligence import (
    TrafficChannelSelection,
    classify_traffic_snapshot,
)


def main(argv: list[str] | None = None) -> int:
    """Print bounded public preview and unverified traffic candidates only."""
    parser = argparse.ArgumentParser(description="Read-only local MeshCore public preview")
    parser.add_argument("--socket", required=True, type=Path)
    parser.add_argument("--credential", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--traffic-slot", type=int, default=1)
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= 100:
        parser.error("limit must be between 1 and 100")
    try:
        approved = TrafficChannelSelection(args.traffic_slot, "#traffic")
        messages = MeshcorePublicConsumer(
            args.socket, args.credential
        ).preview(limit=args.limit)
        candidate_by_id = {
            candidate.broker_message_id: candidate.incident
            for candidate in classify_traffic_snapshot(messages, approved)
        }
    except (MeshcoreConsumerError, ValueError) as exc:
        # The exception text must never include a bearer or a private frame.
        parser.exit(1, f"MeshCore public preview unavailable: {exc}\n")
    document = {
        "schema": "meshcore/public-preview/v1",
        "acknowledged": False,
        "items": [
            {
                "id": item.message_id,
                "channel": item.channel_name,
                "slot": item.channel_slot,
                "text": item.text,
                "received_at_utc": item.received_at.isoformat(),
                "traffic_candidate_category": (
                    candidate_by_id[item.message_id].category.value
                    if item.message_id in candidate_by_id else None
                ),
                "sender_verified": False,
                "location_verified": False,
            }
            for item in messages
        ],
    }
    print(json.dumps(document, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
