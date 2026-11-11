"""Offline-only study of MeshCore companion push notifications.

No hardware transport or outgoing command support. Not production-integrated.
"""

from dataclasses import dataclass
from enum import Enum


class NotificationKind(str, Enum):
    """Public-key-only notifications documented by MeshCore."""

    ADVERTISEMENT = "advertisement"
    PATH_UPDATED = "path_updated"


@dataclass(frozen=True, slots=True)
class IdentityNotification:
    """Opaque identity evidence; never imply an observed full routing path."""

    kind: NotificationKind
    public_key: bytes

    def __post_init__(self) -> None:
        if len(self.public_key) != 32:
            raise ValueError("MeshCore public key must contain exactly 32 bytes")


def parse_identity_notification(frame: bytes) -> IdentityNotification | None:
    """Parse only exact-length inbound identity frames.

    Unknown frames, messages, malformed frames and payload extensions are
    ignored rather than stored. Format: 1-byte push code + 32-byte key.
    """
    if len(frame) != 33:
        return None
    kind = {
        0x80: NotificationKind.ADVERTISEMENT,
        0x81: NotificationKind.PATH_UPDATED,
    }.get(frame[0])
    if kind is None:
        return None
    return IdentityNotification(kind=kind, public_key=bytes(frame[1:]))
