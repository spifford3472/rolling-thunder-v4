"""Inbound-only MeshCore v1.17.1 USB serial frame decoder.

The upstream ArduinoSerialInterface sends '>' + two length bytes + payload.
This pure decoder provides no port, writer, framing encoder or RF command path.
"""

from collections import deque

_MAX_PAYLOAD = 176
_MAX_PENDING = 8192


class MeshcoreInboundFrames:
    """Recover valid bounded frames from a byte stream, ignoring noise."""

    def __init__(self) -> None:
        self._pending = bytearray()
        self.discarded_bytes = 0
        self.invalid_frames = 0

    def feed(self, chunk: bytes) -> tuple[bytes, ...]:
        """Decode complete frames and retain only a bounded incomplete suffix."""
        self._pending.extend(chunk)
        decoded: deque[bytes] = deque()
        while self._pending:
            start = self._pending.find(b">")
            if start < 0:
                self.discarded_bytes += len(self._pending)
                self._pending.clear()
                break
            if start:
                self.discarded_bytes += start
                del self._pending[:start]
            if len(self._pending) < 3:
                break
            frame_length = int.from_bytes(self._pending[1:3], "little")
            if frame_length < 1 or frame_length > _MAX_PAYLOAD:
                self.invalid_frames += 1
                del self._pending[:3]
                continue
            if len(self._pending) < 3 + frame_length:
                break
            decoded.append(bytes(self._pending[3 : 3 + frame_length]))
            del self._pending[: 3 + frame_length]
        if len(self._pending) > _MAX_PENDING:
            # Malformed or stalled input: bounded memory, lose partial data.
            self.discarded_bytes += len(self._pending)
            self._pending.clear()
            self.invalid_frames += 1
        return tuple(decoded)
