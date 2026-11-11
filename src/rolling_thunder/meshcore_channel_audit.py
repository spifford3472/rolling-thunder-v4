"""Parked-only, non-transmitting audit of configured MeshCore channel identities.

The only outgoing command is firmware-local GET_CHANNEL (0x1F). The program
never dequeues a message, modifies radio settings, or prints channel keys.
Run only while the independent collector service is stopped and parked.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from rolling_thunder.meshcore_inbound_frames import MeshcoreInboundFrames
from rolling_thunder.meshcore_serial_service import (
    LocalCommandPort,
    open_meshcore_read_only,
)


@dataclass(frozen=True, slots=True)
class ChannelAuditEntry:
    """Displayable exact slot/name/key fingerprint, never a channel secret."""

    slot: int
    name: str
    secret_sha256: str


class ChannelAuditPort(Protocol):
    """Exclusive, already validated USB transport with local frame I/O."""

    def read(self, count: int) -> bytes:
        """Receive a bounded chunk."""
        ...

    def write(self, data: bytes) -> int | None:
        """Send one pre-approved host-local request."""
        ...

    def close(self) -> None:
        """Release exclusive serial access."""
        ...


def audit_channels(
    port: ChannelAuditPort,
    *,
    max_slot: int = 7,
    timeout_s: float = 3.0,
) -> tuple[ChannelAuditEntry, ...]:
    """Fetch only firmware channel descriptors, rejecting malformed frames.

    A challenge-response per slot means this cannot be used as a generic
    firmware command tool. Channel secrets live only in transient response
    bytes; only their digests leave this function.
    """
    if not 0 <= max_slot <= 7 or not 0.2 <= timeout_s <= 10:
        raise ValueError("Invalid audit bounds")
    decoder = MeshcoreInboundFrames()
    results: list[ChannelAuditEntry] = []
    for slot in range(max_slot + 1):
        command = b"<\x02\x00\x1f" + bytes([slot])
        written = port.write(command)
        if written is not None and written != len(command):
            raise OSError("MeshCore audit short local write")
        deadline = time.monotonic() + timeout_s
        result_found = False
        while time.monotonic() < deadline:
            chunk = port.read(256)
            if not chunk:
                time.sleep(0.01)
                continue
            for payload in decoder.feed(chunk):
                if payload[:1] == b"\x01":
                    # Only explicit ERR_CODE_NOT_FOUND (2) represents an
                    # unconfigured slot; all other errors fail closed.
                    if payload != b"\x01\x02":
                        raise ValueError("MeshCore channel query failed")
                    result_found = True
                    break
                if payload[:1] != b"\x12":
                    continue
                if len(payload) != 50 or payload[1] != slot:
                    raise ValueError("Unexpected channel response identity")
                raw_name, marker, _padding = payload[2:34].partition(b"\x00")
                if not marker:
                    raise ValueError("Invalid channel name termination")
                try:
                    name = raw_name.decode("utf-8", errors="strict")
                except UnicodeDecodeError as error:
                    raise ValueError("Invalid channel name UTF-8") from error
                if not name or any(ord(ch) < 32 for ch in name):
                    raise ValueError("Invalid channel name")
                results.append(ChannelAuditEntry(
                    slot=slot,
                    name=name,
                    secret_sha256=hashlib.sha256(payload[34:50]).hexdigest(),
                ))
                result_found = True
                break
            if result_found:
                break
        if not result_found:
            raise TimeoutError("MeshCore channel query timed out")
    return tuple(results)


def main(argv: list[str] | None = None) -> int:
    """Inspect channel identities locally, without persisting credential bytes."""
    parser = argparse.ArgumentParser(
        description="Parked MeshCore channel metadata audit; no RF commands"
    )
    parser.add_argument("--device", type=Path, required=True)
    options = parser.parse_args(argv)
    port = open_meshcore_read_only(options.device)
    try:
        if not isinstance(port, LocalCommandPort):
            raise TypeError("Device does not support local command replies")
        details = audit_channels(port)
    finally:
        port.close()
    # This output includes channel *names* and fingerprints, not raw keys.
    # Treat it as local station metadata; do not paste into public chats.
    print(json.dumps([asdict(item) for item in details], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
