"""Offline Tron command boundary tests: no audio or radio hardware required."""

from rolling_thunder.tron_commands import TronIntent, command_grammar, parse_tron_command


def test_only_supported_read_only_intents_parse() -> None:
    assert parse_tron_command("Tron help") == TronIntent("help")
    assert parse_tron_command("TRON   status") == TronIntent("status")
    assert parse_tron_command("tron current screen") == TronIntent("current_screen")
    assert parse_tron_command("tron show ft eight") == TronIntent("navigate", "ft8")
    for target in (
        "pota", "dx", "browse", "ft8", "weather", "repeaters",
        "dmr", "log", "settings",
    ):
        assert parse_tron_command(f"tron show {target}") == TronIntent("navigate", target)


def test_station_navigation_and_selection_phrases_parse_exactly() -> None:
    expected = {
        "tron next": "next",
        "tron next station": "next",
        "tron previous": "previous",
        "tron previous station": "previous",
        "tron first": "first",
        "tron first station": "first",
        "tron last": "last",
        "tron last station": "last",
        "tron select": "select_station",
        "tron select station": "select_station",
        "tron choose": "select_station",
        "tron choose station": "select_station",
    }
    for phrase, action in expected.items():
        assert parse_tron_command(phrase) == TronIntent(action)


def test_unrecognized_or_unsafe_requests_fail_closed() -> None:
    for utterance in (
        "", "open ft8", "tron", "tron system status", "tron where am i",
        "tron transmit", "tron call cq", "tron log contact", "tron commit",
        "tron press ptt", "tron change power", "tron open", "tron open secret",
        "tron show home", "tron show ft8 now", "tron start callsign capture",
        "tron approve qso", "tron reject qso", "tron accept qso",
        "tron next station please", "tron first station now", "tron select and transmit",
        "not tron help", "tron help and transmit",
    ):
        assert parse_tron_command(utterance) is None


def test_grammar_contains_only_explicit_supported_phrases() -> None:
    grammar = command_grammar()
    assert grammar[-1] == "[unk]"
    assert len(grammar) == len(set(grammar))
    assert "tron show ft8" in grammar
    assert "tron show browse" in grammar
    assert "tron show weather" in grammar
    assert "tron show repeaters" in grammar
    assert "tron show dmr" in grammar
    assert "tron next station" in grammar
    assert "tron select station" in grammar
    assert "tron help" in grammar
    assert all("transmit" not in phrase and "callsign" not in phrase for phrase in grammar)
