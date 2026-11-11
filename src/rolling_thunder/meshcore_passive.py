"""Pure, offline-only parser for MeshCore v1.17.1 unsolicited notifications.

Input is an already-deframed companion payload. This module cannot open a
serial device, control a radio, or issue any outgoing MeshCore command.
"""

from dataclasses import dataclass
from enum import StrEnum

_MAX_PATH_SIZE = 64
_NEW_ADVERT_LENGTH = 1 + 32 + 1 + 1 + 1 + _MAX_PATH_SIZE + 32 + 4 + 4 + 4 + 4


class ObservationType(StrEnum):
    """Observed notification types; a path update is not a received route."""

    ADVERTISEMENT = "advertisement"
    NEW_ADVERTISEMENT = "new_advertisement"
    PATH_UPDATED = "path_updated"


@dataclass(frozen=True, slots=True)
class MeshcoreObservation:
    """Only safe, verified identity metadata from a notification."""

    event_type: ObservationType
    public_key_hex: str
    node_type_code: int | None = None
    advertised_name: str | None = None
    advertised_timestamp: int | None = None
    # Signal metrics are not present in supported push frames.
    rssi_dbm: float | None = None
    snr_db: float | None = None
    # A cached outbound path is not an observed inbound routing path.
    observed_path: bytes | None = None


def _safe_name(value: bytes) -> str | None:
    """Decode a bounded advertised name without accepting control characters."""
    value = value.split(b"\x00", 1)[0]
    try:
        decoded = value.decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError:
        return None
    if not decoded or any(ord(ch) < 32 or ord(ch) == 127 for ch in decoded):
        return None
    return decoded


def parse_passive_notification(payload: bytes) -> MeshcoreObservation | None:
    """Parse exactly the supported push payloads; reject all other traffic.

    Based on meshcore-dev/MeshCore companion-v1.17.1 MyMesh.cpp:
    0x80/0x81 are 33-byte full-key notifications;
    0x8A is writeContactRespFrame with 32-byte key, contact type,
    flags, cached outbound path length and 64-byte path, 32-byte name,
    advertisement timestamp, advertised coordinates and lastmod.

    Deliberately discard contact routing fields and peer coordinates: they
    are not proven receiver-observed paths or receiver GPS.
    """
    if not payload:
        return None
    code = payload[0]
    if code in (0x80, 0x81):
        if len(payload) != 33:
            return None
        kind = (
            ObservationType.ADVERTISEMENT
            if code == 0x80
            else ObservationType.PATH_UPDATED
        )
        return MeshcoreObservation(kind, payload[1:33].hex())
    if code != 0x8A or len(payload) != _NEW_ADVERT_LENGTH:
        return None

    # Exact offsets are derived from writeContactRespFrame.
    key = payload[1:33]
    node_type_code = payload[33]
    name = _safe_name(payload[100:132])
    advert_at = int.from_bytes(payload[132:136], "little")
    return MeshcoreObservation(
        event_type=ObservationType.NEW_ADVERTISEMENT,
        public_key_hex=key.hex(),
        node_type_code=node_type_code,
        advertised_name=name,
        advertised_timestamp=advert_at or None,
    )
