"""Offline Tron command boundary tests: no audio or radio hardware required."""

from rolling_thunder.tron_commands import TronIntent, command_grammar, parse_tron_command


def test_only_supported_read_only_intents_parse() -> None:
    assert parse_tron_command("Tron help") == TronIntent("help")
    assert parse_tron_command("TRON   status") == TronIntent("status")
    assert parse_tron_command("tron current screen") == TronIntent("current_screen")
    assert parse_tron_command("tron show ft eight") == TronIntent("navigate", "ft8")
    for target in ("pota", "dx", "ft8", "log", "settings"):
        assert parse_tron_command(f"tron show {target}") == TronIntent("navigate", target)


def test_unrecognized_or_unsafe_requests_fail_closed() -> None:
    for utterance in (
        "", "open ft8", "tron", "tron system status", "tron where am i",
        "tron transmit", "tron call cq", "tron log contact", "tron commit",
        "tron press ptt", "tron change power", "tron open", "tron open secret",
        "tron show home", "tron show ft8 now", "tron start callsign capture",
        "not tron help", "tron help and transmit",
    ):
        assert parse_tron_command(utterance) is None


def test_grammar_contains_only_explicit_supported_phrases() -> None:
    grammar = command_grammar()
    assert grammar[-1] == "[unk]"
    assert len(grammar) == len(set(grammar))
    assert "tron show ft8" in grammar
    assert "tron help" in grammar
    assert all("transmit" not in phrase and "callsign" not in phrase for phrase in grammar)
