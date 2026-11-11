"""Strict MeshCore v1.16 public-channel protocol regression/fuzz tests."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest

from rolling_thunder.meshcore_public_intake_protocol import (
    ApprovedPublicChannel,
    VerifiedChannel,
    classify_queue_response_type,
    decode_verified_channel_text,
    verify_channel_info,
)

SECRET = bytes(range(16))
APPROVED = ApprovedPublicChannel(
    slot=3,
    name="#traffic",
    secret_sha256=hashlib.sha256(SECRET).hexdigest(),
    approved_for_public_intake=True,
)
VERIFIED = VerifiedChannel(slot=3, name="#traffic")
TIMESTAMP = 1_794_405_600


def _info(
    *, slot: int = 3, name: bytes = b"#traffic", secret: bytes = SECRET
) -> bytes:
    return bytes([0x12, slot]) + name.ljust(32, b"\x00") + secret


def _message(*, v3: bool = True, slot: int = 3, text: bytes = b"Accident I-71") -> bytes:
    header = (
        bytes([0x11, 0xE0, 0, 0, slot, 0xFF, 0])
        if v3 else bytes([0x08, slot, 0xFF, 0])
    )
    return header + TIMESTAMP.to_bytes(4, "little") + text


def test_exact_channel_identity_attestation_and_no_secret_in_output() -> None:
    identity = verify_channel_info(_info(), APPROVED)
    assert identity == VERIFIED
    assert SECRET.hex() not in repr(identity)


@pytest.mark.parametrize(
    "response",
    [
        _info(slot=2),
        _info(name=b"#skywarn"),
        _info(secret=b"\x00" * 16),
        _info()[:-1],
        _info() + b"\x00",
        bytes([0x05]) + _info()[1:],
        _info(name=b"abc\x00evil"),
        _info(name=b"\xff"),
    ],
)
def test_channel_attestation_fails_closed(response: bytes) -> None:
    assert verify_channel_info(response, APPROVED) is None


def test_operator_approval_required() -> None:
    denied = ApprovedPublicChannel(
        APPROVED.slot, APPROVED.name, APPROVED.secret_sha256, False
    )
    assert verify_channel_info(_info(), denied) is None


def test_channel_message_v3_and_legacy() -> None:
    for modern in (True, False):
        decoded = decode_verified_channel_text(_message(v3=modern), VERIFIED)
        assert decoded is not None
        assert decoded.slot == 3
        assert decoded.text == "Accident I-71"
        assert decoded.claimed_at == datetime.fromtimestamp(TIMESTAMP, UTC)
        assert decoded.snr_db == -8.0 if modern else decoded.snr_db is None


@pytest.mark.parametrize(
    "response",
    [
        b"",
        _message(slot=2),
        _message(text=b""),
        _message(text=b"\xff"),
        _message(text=b"bad\x00payload"),
        _message(text=b"hi\x01"),
        _message(text=b" a " * 200),
        _message()[:-1][:10],
        _message() + b"x" * 200,
        _message(v3=False, slot=5),
        bytes([0x07]) + _message()[1:],
        bytes([0x10]) + _message()[1:],
        bytes([0x1B]) + _message()[1:],
        bytes([0x11, 0xE0, 1, 0]) + _message()[4:],
    ],
)
def test_rejects_malformed_untrusted_and_private_frames(response: bytes) -> None:
    assert decode_verified_channel_text(response, VERIFIED) is None


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (bytes([0x07]) + b"private", "private_do_not_store"),
        (bytes([0x10]) + b"private", "private_do_not_store"),
        (bytes([0x1B]) + b"binary", "binary_do_not_store"),
        (_message(), "channel_requires_verification"),
        (_message(v3=False), "channel_requires_verification"),
        (bytes([0x0A]), "empty"),
        (b"", "malformed"),
        (b"\x83", "unsupported"),
    ],
)
def test_queue_routing_does_not_inspect_private_content(
    payload: bytes, expected: str
) -> None:
    assert classify_queue_response_type(payload) == expected


def test_channel_descriptor_validation() -> None:
    with pytest.raises(ValueError):
        ApprovedPublicChannel(9, "traffic", APPROVED.secret_sha256, True)
    with pytest.raises(ValueError):
        ApprovedPublicChannel(0, "traffic", "secret-in-plaintext", True)
    with pytest.raises(ValueError):
        ApprovedPublicChannel(0, "", APPROVED.secret_sha256, True)


def test_fuzz_all_first_bytes_cannot_create_other_types() -> None:
    for opcode in range(256):
        msg = bytes([opcode]) + _message()[1:]
        decoded = decode_verified_channel_text(msg, VERIFIED)
        assert (decoded is not None) == (opcode in (0x08, 0x11) and opcode == 0x11)


def test_no_encoder_or_side_effecting_io_exported() -> None:
    import rolling_thunder.meshcore_public_intake_protocol as protocol

    assert not hasattr(protocol, "send")
    assert not hasattr(protocol, "dequeue")
    assert not hasattr(protocol, "open_serial")
