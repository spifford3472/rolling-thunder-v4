"""Pure byte-stream parser test fixtures for MeshCore UART push traffic."""

from rolling_thunder.meshcore_inbound_frames import MeshcoreInboundFrames


def _frame(payload: bytes) -> bytes:
    return b">" + len(payload).to_bytes(2, "little") + payload


def test_fragmented_and_concatenated_frames() -> None:
    decoder = MeshcoreInboundFrames()
    first = b"\x80" + bytes(range(32))
    second = b"\x81" + bytes(range(32))
    stream = _frame(first) + _frame(second)
    assert decoder.feed(stream[:2]) == ()
    assert decoder.feed(stream[2:15]) == ()
    assert decoder.feed(stream[15:]) == (first, second)


def test_garbage_and_oversized_frame_recovery() -> None:
    decoder = MeshcoreInboundFrames()
    event = b"\x80" + bytes(32)
    received = decoder.feed(
        b"noise" + b">\xff\x7f" + b"junk" + _frame(event)
    )
    assert received == (event,)
    assert decoder.discarded_bytes >= 5
    assert decoder.invalid_frames == 1


def test_invalid_zero_length_frame() -> None:
    decoder = MeshcoreInboundFrames()
    event = b"\x81" + bytes(32)
    assert decoder.feed(b">\x00\x00" + _frame(event)) == (event,)
    assert decoder.invalid_frames == 1


def test_176_byte_firmware_limit() -> None:
    decoder = MeshcoreInboundFrames()
    payload = bytes(range(176))
    assert decoder.feed(_frame(payload)) == (payload,)


def test_input_never_creates_outgoing_frames() -> None:
    decoder = MeshcoreInboundFrames()
    assert decoder.feed(b"<\x01\x00\x07") == ()
    assert decoder.discarded_bytes == 4
