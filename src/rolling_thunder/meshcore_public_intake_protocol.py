"""Non-actuating MeshCore v1.16 public-channel decoding and attestation.

The installed companion-v1.16.0 firmware (07a3ca9e) stores channel text in
the *shared* offline message queue. This module never dequeues, opens USB,
transmits RF, persists message content, or retains channel secrets.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from datetime import UTC, datetime

_CHANNEL_INFO = 0x12
_CHANNEL_TEXT_LEGACY = 0x08
_CHANNEL_TEXT_V3 = 0x11
_NO_MESSAGES = 0x0A
_PRIVATE_TYPES = frozenset((0x07, 0x10))
_CHANNEL_DATA = 0x1B
_MAX_FRAME_BYTES = 172
_INDEX_RANGE = range(8)
_DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True, slots=True)
class ApprovedPublicChannel:
    """Out-of-band operator-approved channel descriptor, never inferred by name.

    The SHA-256 fingerprint is calculated outside this service using the
    configured 16-byte key and stored without the original secret. It is not
    proof that a community channel has no access restrictions; that designation
    requires explicit operator verification.
    """

    slot: int
    name: str
    secret_sha256: str
    approved_for_public_intake: bool

    def __post_init__(self) -> None:
        if self.slot not in _INDEX_RANGE:
            raise ValueError("Invalid channel slot")
        if not self.name or len(self.name.encode("utf-8")) > 31:
            raise ValueError("Invalid approved channel name")
        if not _DIGEST_RE.fullmatch(self.secret_sha256):
            raise ValueError("Invalid channel fingerprint")


@dataclass(frozen=True, slots=True)
class VerifiedChannel:
    """Runtime identity, with key material intentionally omitted."""

    slot: int
    name: str


@dataclass(frozen=True, slots=True)
class ChannelText:
    """Unverified sender-authorship; timestamp comes from the remote sender."""

    slot: int
    text: str
    claimed_at: datetime
    snr_db: float | None
    path_length_code: int


def verify_channel_info(
    response: bytes, approved: ApprovedPublicChannel
) -> VerifiedChannel | None:
    """Attest index, name and secret against an explicitly approved fingerprint.

    Firmware returns the channel secret in bytes 34-49. Process it only within
    a local transient buffer and never return or log it. Channel names alone
    are insufficient to establish provenance.
    """
    if not approved.approved_for_public_intake or len(response) != 50:
        return None
    if response[0] != _CHANNEL_INFO or response[1] != approved.slot:
        return None
    name_bytes = response[2:34]
    name_bytes, terminator, _unused_padding = name_bytes.partition(b"\x00")
    # v1.16 uses strcpy() then advances 32 bytes without zeroing padding;
    # stale bytes after NUL are not part of the name or an identity signal.
    if not terminator:
        return None
    try:
        name = name_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return None
    if name != approved.name:
        return None
    fingerprint = hashlib.sha256(response[34:50]).hexdigest()
    if not hmac.compare_digest(fingerprint, approved.secret_sha256):
        return None
    return VerifiedChannel(slot=approved.slot, name=name)


def decode_verified_channel_text(
    payload: bytes, verified: VerifiedChannel
) -> ChannelText | None:
    """Accept only ordinary channel text for a previously attested slot.

    Contact/DM (0x07/0x10), channel datagrams (0x1B), malformed fields,
    unsupported text types and data for different slots are rejected. This
    does not reclaim frames from a firmware queue or prove sender identity.
    """
    if not payload or len(payload) > _MAX_FRAME_BYTES:
        return None
    code = payload[0]
    if code not in (_CHANNEL_TEXT_LEGACY, _CHANNEL_TEXT_V3):
        return None
    if code == _CHANNEL_TEXT_V3:
        if len(payload) < 12 or payload[2:4] != b"\x00\x00":
            return None
        snr_db: float | None = int.from_bytes(
            payload[1:2], "little", signed=True
        ) / 4.0
        offset = 4
    else:
        if len(payload) < 9:
            return None
        snr_db = None
        offset = 1
    if payload[offset] != verified.slot or payload[offset + 2] != 0:
        return None
    path_code = payload[offset + 1]
    # 0xFF is *direct incoming*, otherwise an encoded flood path length,
    # not a route that can be used for transmitting.
    if path_code != 0xFF and (path_code & 0x3F) > 15:
        return None
    when = int.from_bytes(payload[offset + 3:offset + 7], "little")
    if when == 0:
        return None
    try:
        text = payload[offset + 7:].decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return None
    if (
        not text.strip()
        or "\x00" in text
        or any(ord(ch) < 32 and ch not in "\t\n" for ch in text)
        or len(text) > 512
    ):
        return None
    return ChannelText(
        slot=verified.slot,
        text=text,
        claimed_at=datetime.fromtimestamp(when, tz=UTC),
        snr_db=snr_db,
        path_length_code=path_code,
    )


def classify_queue_response_type(payload: bytes) -> str:
    """Route without inspecting/storing private payloads.

    Dequeue is destructive in v1.16 firmware, so a future serial policy must
    resolve loss of nonpublic messages *before* calling the dequeue command.
    """
    if not payload:
        return "malformed"
    if payload[0] in _PRIVATE_TYPES:
        return "private_do_not_store"
    if payload[0] == _CHANNEL_DATA:
        return "binary_do_not_store"
    if payload[0] in (_CHANNEL_TEXT_LEGACY, _CHANNEL_TEXT_V3):
        return "channel_requires_verification"
    if payload == bytes((_NO_MESSAGES,)):
        return "empty"
    return "unsupported"
