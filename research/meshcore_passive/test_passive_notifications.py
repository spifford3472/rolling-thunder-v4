"""Synthetic-only tests: never communicate with a radio or USB device."""

from passive_notifications import NotificationKind, parse_identity_notification


def test_advert_preserves_full_identity():
    key = bytes(range(32))
    parsed = parse_identity_notification(bytes([0x80]) + key)
    assert parsed is not None
    assert parsed.kind is NotificationKind.ADVERTISEMENT
    assert parsed.public_key == key


def test_path_update_does_not_invent_route():
    parsed = parse_identity_notification(bytes([0x81]) + bytes(range(32)))
    assert parsed is not None
    assert parsed.kind is NotificationKind.PATH_UPDATED
    assert not hasattr(parsed, "route")


def test_identity_collisions_not_caused_by_short_prefix():
    key_a = bytes([1] * 31 + [2])
    key_b = bytes([1] * 31 + [3])
    a = parse_identity_notification(b"\x80" + key_a)
    b = parse_identity_notification(b"\x80" + key_b)
    assert a is not None and b is not None
    assert a.public_key != b.public_key


def test_unknown_message_and_payload_ignored():
    for code in (0x07, 0x08, 0x83, 0x88, 0x8A, 0xFF):
        assert parse_identity_notification(bytes([code]) + bytes(32)) is None


def test_truncation_and_extension_rejected():
    base = b"\x80" + bytes(range(32))
    for n in range(len(base)):
        assert parse_identity_notification(base[:n]) is None
    assert parse_identity_notification(base + b"\x00") is None


def test_does_not_require_serial():
    import inspect

    import passive_notifications
    assert "serial" not in inspect.getsource(passive_notifications).split("from dataclasses")[1]
