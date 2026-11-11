"""Offline MeshCore tests using synthetic, already-deframed payloads."""

from rolling_thunder.meshcore_passive import (
    ObservationType,
    parse_passive_notification,
)


def _new_advert(key: bytes, name: bytes = b"Repeater1") -> bytes:
    # 0x8A + pubkey32 + type1 + flags1 + pathlen1 + path64 +
    # name32 + timestamp4 + peer lat4 + peer lon4 + lastmod4.
    return (
        bytes([0x8A]) + key + bytes([2, 0, 7]) + bytes(range(64))
        + name.ljust(32, b"\0") + (1234).to_bytes(4, "little")
        + (1111).to_bytes(4, "little", signed=True)
        + (2222).to_bytes(4, "little", signed=True)
        + (5678).to_bytes(4, "little")
    )


def test_full_identity_and_path_notification_no_route() -> None:
    key = bytes(range(32))
    advert = parse_passive_notification(b"\x80" + key)
    path = parse_passive_notification(b"\x81" + key)
    assert advert is not None and path is not None
    assert advert.public_key_hex == key.hex()
    assert path.event_type == ObservationType.PATH_UPDATED
    assert advert.observed_path is None and path.observed_path is None


def test_new_advert_metadata_and_no_cached_route_leak() -> None:
    key = bytes(range(32))
    event = parse_passive_notification(_new_advert(key))
    assert event is not None
    assert event.event_type == ObservationType.NEW_ADVERTISEMENT
    assert event.node_type_code == 2
    assert event.advertised_name == "Repeater1"
    assert event.advertised_timestamp == 1234
    assert event.observed_path is None
    assert event.rssi_dbm is None and event.snr_db is None
    assert event.public_key_hex == key.hex()


def test_invalid_utf8_name_does_not_discard_node() -> None:
    event = parse_passive_notification(_new_advert(bytes(32), b"\xff"))
    assert event is not None and event.advertised_name is None


def test_short_prefix_collision_is_not_merged() -> None:
    first = parse_passive_notification(b"\x80" + bytes(31) + b"\x01")
    second = parse_passive_notification(b"\x80" + bytes(31) + b"\x02")
    assert first is not None and second is not None
    assert first.public_key_hex != second.public_key_hex


def test_other_frames_and_bad_lengths_rejected() -> None:
    valid = _new_advert(bytes(range(32)))
    assert len(valid) == 148
    for length in range(len(valid)):
        assert parse_passive_notification(valid[:length]) is None
    assert parse_passive_notification(valid + b"\x00") is None
    for code in (0, 1, 7, 0x82, 0x83, 0x88, 0x89, 0x8B, 0xFF):
        assert parse_passive_notification(bytes([code]) + bytes(32)) is None
