"""Tests for MMDVMHost DMR activity parsing and live-call tracking."""

from datetime import UTC, datetime

from rolling_thunder.dmr_activity import (
    DmrActivitySource,
    DmrEventKind,
    DmrLiveCallTracker,
    dmr_talkgroup_from_target,
    parse_mmdvm_dmr_line,
)


def test_parse_network_voice_start_from_observed_wpsd_log() -> None:
    event = parse_mmdvm_dmr_line(
        "M: 2026-08-16 00:06:05.816 DMR Slot 1, "
        "received network voice header from KC9KPJ to TG 3100"
    )

    assert event is not None
    assert event.kind is DmrEventKind.VOICE_START
    assert event.occurred_at == datetime(2026, 8, 16, 0, 6, 5, 816000, tzinfo=UTC)
    assert event.slot == 1
    assert event.source is DmrActivitySource.NETWORK
    assert event.callsign == "KC9KPJ"
    assert event.target == "TG 3100"


def test_parse_talker_alias_from_observed_wpsd_log() -> None:
    event = parse_mmdvm_dmr_line(
        'M: 2026-08-16 00:06:08.507 DMR Slot 1, Talker Alias "KC9KPJ KC9KPJ"'
    )

    assert event is not None
    assert event.kind is DmrEventKind.TALKER_ALIAS
    assert event.slot == 1
    assert event.talker_alias == "KC9KPJ KC9KPJ"


def test_parse_network_voice_end_from_observed_wpsd_log() -> None:
    event = parse_mmdvm_dmr_line(
        "M: 2026-08-16 00:07:22.084 DMR Slot 1, "
        "received network end of voice transmission from KC9KPJ to TG 3100, "
        "14.2 seconds, 0% packet loss, BER: 0.0%"
    )

    assert event is not None
    assert event.kind is DmrEventKind.VOICE_END
    assert event.source is DmrActivitySource.NETWORK
    assert event.callsign == "KC9KPJ"
    assert event.target == "TG 3100"
    assert event.duration_s == 14.2
    assert event.packet_loss_percent == 0.0
    assert event.ber_percent == 0.0


def test_parse_ignores_non_dmr_and_unknown_dmr_lines() -> None:
    assert parse_mmdvm_dmr_line("I: unrelated startup line") is None
    assert (
        parse_mmdvm_dmr_line(
            "M: 2026-08-16 00:06:08.507 DMR Slot 1, some future unsupported event"
        )
        is None
    )


def test_tracker_follows_start_alias_and_end_sequence() -> None:
    tracker = DmrLiveCallTracker()

    start = parse_mmdvm_dmr_line(
        "M: 2026-08-16 00:06:05.816 DMR Slot 1, "
        "received network voice header from KC9KPJ to TG 3100"
    )
    alias = parse_mmdvm_dmr_line(
        'M: 2026-08-16 00:06:08.507 DMR Slot 1, Talker Alias "KC9KPJ KC9KPJ"'
    )
    end = parse_mmdvm_dmr_line(
        "M: 2026-08-16 00:07:22.084 DMR Slot 1, "
        "received network end of voice transmission from KC9KPJ to TG 3100, "
        "14.2 seconds, 0% packet loss, BER: 0.0%"
    )

    assert start is not None
    assert alias is not None
    assert end is not None

    active = tracker.apply(start)
    assert active is not None
    assert active.active
    assert active.identity.callsign == "KC9KPJ"
    assert tracker.active_for_slot(1) == active

    enriched = tracker.apply(alias)
    assert enriched is not None
    assert enriched.talker_alias == "KC9KPJ KC9KPJ"
    assert tracker.active_for_slot(1) == enriched

    completed = tracker.apply(end)
    assert completed is not None
    assert not completed.active
    assert completed.duration_s == 14.2
    assert completed.packet_loss_percent == 0.0
    assert completed.ber_percent == 0.0
    assert tracker.active_for_slot(1) is None


def test_tracker_keeps_timeslots_independent() -> None:
    tracker = DmrLiveCallTracker()

    slot_one = parse_mmdvm_dmr_line(
        "M: 2026-08-16 00:06:05.816 DMR Slot 1, "
        "received network voice header from KC9KPJ to TG 3100"
    )
    slot_two = parse_mmdvm_dmr_line(
        "M: 2026-08-16 00:06:06.816 DMR Slot 2, "
        "received network voice header from W3GSI to TG 91"
    )

    assert slot_one is not None
    assert slot_two is not None

    tracker.apply(slot_one)
    tracker.apply(slot_two)

    assert [call.identity.slot for call in tracker.active_calls] == [1, 2]
    assert tracker.active_for_slot(1) is not None
    assert tracker.active_for_slot(2) is not None


def test_tracker_does_not_close_active_call_with_mismatched_end_event() -> None:
    tracker = DmrLiveCallTracker()

    start = parse_mmdvm_dmr_line(
        "M: 2026-08-16 00:06:05.816 DMR Slot 1, "
        "received network voice header from KC9KPJ to TG 3100"
    )
    wrong_end = parse_mmdvm_dmr_line(
        "M: 2026-08-16 00:07:22.084 DMR Slot 1, "
        "received network end of voice transmission from W3GSI to TG 3100, "
        "14.2 seconds, 0% packet loss, BER: 0.0%"
    )

    assert start is not None
    assert wrong_end is not None

    tracker.apply(start)
    assert tracker.apply(wrong_end) is None
    assert tracker.active_for_slot(1) is not None


def test_parser_accepts_rf_source_without_assuming_network() -> None:
    event = parse_mmdvm_dmr_line(
        "M: 2026-08-16 00:06:05.816 DMR Slot 2, "
        "received RF voice header from KI5VNB to TG 3100"
    )

    assert event is not None
    assert event.source is DmrActivitySource.RF
    assert event.slot == 2
    assert event.callsign == "KI5VNB"


def test_talkgroup_target_parser_is_not_tied_to_tg3100() -> None:
    assert dmr_talkgroup_from_target("TG 91") == 91
    assert dmr_talkgroup_from_target("received on TG 3139") == 3139
    assert dmr_talkgroup_from_target("Private Call 91") is None
