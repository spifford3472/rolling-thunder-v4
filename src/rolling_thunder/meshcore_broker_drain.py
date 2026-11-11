"""Single-flight, local-serial-only MesaCore offline-queue drain controller.

The installed v1.16 firmware's 0x0A command pops the next message of *any*
kind. Store the entire dequeued reply synchronously before the next 0x0A.
On timeout, write failure or identity mismatch, fail closed without retrying
blindly. This module cannot send any MeshCore over-the-air packet.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from rolling_thunder.meshcore_message_broker import MeshcoreMessageBroker
from rolling_thunder.meshcore_public_intake_protocol import (
    ApprovedPublicChannel,
    VerifiedChannel,
    decode_verified_channel_text,
    verify_channel_info,
)

_LOGGER = logging.getLogger(__name__)
_DEQUEUE = b"<\x01\x00\x0a"
_MAX_CHANNELS = 8
_MAX_BURST = 16
_WAIT_SECONDS = 3.0
_EXPECTED_QUEUE_RESPONSES = frozenset({0x07, 0x08, 0x10, 0x11, 0x1B})


class SerialFrameWriter(Protocol):
    """One already-open exclusive validated MeshCore transport."""

    def write(self, payload: bytes) -> int | None:
        """Write a local companion command, not a radio payload."""
        ...


@dataclass(frozen=True, slots=True)
class DrainStatus:
    """Counters only; no text, channel secrets or private payloads."""

    enabled: bool
    connected: bool
    ready: bool
    fault: str | None
    saved: int
    private_saved: int
    public_saved: int
    quarantine_saved: int
    waiting_for_response: bool


class MeshcoreBrokerDrain:
    """Bounded serial command state machine used by the sole serial owner."""

    def __init__(
        self,
        inbox: MeshcoreMessageBroker,
        approved: tuple[ApprovedPublicChannel, ...],
    ) -> None:
        if not approved or len(approved) > _MAX_CHANNELS:
            raise ValueError("At least one approved channel is required")
        if len({item.slot for item in approved}) != len(approved):
            raise ValueError("Duplicate channel slot")
        if not all(item.approved_for_public_intake for item in approved):
            raise ValueError("Unapproved public channel")
        self._inbox = inbox
        self._approved = tuple(sorted(approved, key=lambda item: item.slot))
        self._verified: dict[int, VerifiedChannel] = {}
        self._connected = False
        self._fault: str | None = None
        self._pending: str | None = None
        self._deadline = 0.0
        self._channel_pos = 0
        self._need_drain = False
        self._burst = 0
        self._saved = 0
        self._public = 0
        self._private = 0
        self._quarantine = 0

    def connected(self) -> None:
        """Forget attestations after reconnect; verify each channel anew."""
        self._verified.clear()
        self._connected = True
        self._fault = None
        self._pending = None
        self._channel_pos = 0
        self._need_drain = True
        self._burst = 0

    def disconnected(self) -> None:
        """Never trust pending replies or cached key attestations on reconnect."""
        self._connected = False
        self._verified.clear()
        self._pending = None

    def _abort(self, reason: str) -> None:
        """Stop new destructive dequeues; never log a response payload."""
        self._fault = reason
        self._pending = None
        self._need_drain = False
        _LOGGER.error("MeshCore message intake stopped: %s", reason)

    def receive(self, payload: bytes) -> bool:
        """Handle a deframed response or push without revealing private data."""
        if not self._connected:
            return False
        if payload == b"\x83":
            self._need_drain = True
            return True
        if self._pending == "channel":
            if payload[:1] == b"\x12":
                expected = self._approved[self._channel_pos]
                verified = verify_channel_info(payload, expected)
                if verified is None:
                    self._abort("channel_identity_mismatch")
                else:
                    self._verified[verified.slot] = verified
                    self._channel_pos += 1
                    self._pending = None
                return True
            if payload[:1] == b"\x01":
                self._abort("channel_query_failed")
                return True
            return False
        if self._pending != "dequeue":
            return False
        if payload == b"\x0a":
            self._pending = None
            self._need_drain = False
            self._burst = 0
            return True
        if payload[:1] == b"\x01":
            self._abort("firmware_dequeue_error")
            return True
        if not payload or payload[0] not in _EXPECTED_QUEUE_RESPONSES:
            return False
        # Never queue on a second worker: firmware already removed the message.
        # A successful return below means the SQLite transaction committed.
        try:
            self._inbox.store(
                payload, received_at=datetime_now(), verified_channels=self._verified
            )
        except (sqlite3.Error, OSError, ValueError, RuntimeError):
            self._abort("inbox_commit_failed")
            return True
        if payload[0] in (0x07, 0x10):
            self._private += 1
        elif (
            payload[0] in (0x08, 0x11)
            and (
                verified := self._verified.get(
                    payload[4 if payload[0] == 0x11 else 1]
                )
            ) is not None
            and decode_verified_channel_text(payload, verified) is not None
        ):
            self._public += 1
        else:
            self._quarantine += 1
        self._saved += 1
        self._pending = None
        self._need_drain = True
        return True

    def tick(self, writer: SerialFrameWriter) -> None:
        """Issue at most one serial request while awaiting an exact reply."""
        if not self._connected or self._fault is not None:
            return
        now = time.monotonic()
        if self._pending is not None:
            if now > self._deadline:
                self._abort("serial_response_timeout")
            return
        if self._channel_pos < len(self._approved):
            slot = self._approved[self._channel_pos].slot
            command = b"<\x02\x00\x1f" + bytes((slot,))
            self._write_command(writer, command, "channel")
            return
        if not self._need_drain:
            return
        if self._burst >= _MAX_BURST:
            self._burst = 0
            return
        try:
            if not self._inbox.can_accept():
                self._abort("inbox_capacity_exhausted")
                return
        except (sqlite3.Error, OSError, ValueError):
            self._abort("inbox_unavailable")
            return
        self._write_command(writer, _DEQUEUE, "dequeue")
        if self._pending == "dequeue":
            self._burst += 1

    def _write_command(
        self, writer: SerialFrameWriter, command: bytes, response_kind: str
    ) -> None:
        """Only two audited local opcodes are possible in this module."""
        try:
            amount = writer.write(command)
            if amount is not None and amount != len(command):
                self._abort("serial_short_write")
                return
        except (OSError, ValueError):
            self._abort("serial_write_failed")
            return
        self._pending = response_kind
        self._deadline = time.monotonic() + _WAIT_SECONDS

    def status(self) -> DrainStatus:
        """Observe state without accessing any SQLite content."""
        return DrainStatus(
            enabled=True,
            connected=self._connected,
            ready=(
                self._connected and self._fault is None
                and self._channel_pos == len(self._approved)
            ),
            fault=self._fault,
            saved=self._saved,
            private_saved=self._private,
            public_saved=self._public,
            quarantine_saved=self._quarantine,
            waiting_for_response=self._pending is not None,
        )


def datetime_now() -> datetime:
    """Injectable clock boundary for deterministic future intake simulation."""
    return datetime.now(UTC)
