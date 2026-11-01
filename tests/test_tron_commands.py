"""Offline Tron command boundary tests: no audio or radio hardware required."""

from rolling_thunder.tron_commands import TronIntent, command_grammar, parse_tron_command


def test_read_only_intents() -> None:
    assert parse_tron_command("Tron help") == TronIntent("help")
    assert parse_tron_command("TRON   system status") == TronIntent("status")
    assert parse_tron_command("tron where am i") == TronIntent("current_screen")
    assert parse_tron_command("tron open ft eight") == TronIntent("navigate", "ft8")
    assert parse_tron_command("tron go to pota") == TronIntent("navigate", "pota")
    assert parse_tron_command("tron show home") == TronIntent("navigate", "dashboard")


def test_unrecognized_or_unsafe_requests_fail_closed() -> None:
    for utterance in (
        "", "open ft8", "tron", "tron transmit", "tron call cq",
        "tron log contact", "tron commit", "tron press ptt",
        "tron change power", "tron open", "tron open secret",
        "tron open ft8 now", "tron start callsign capture",
        "not tron help", "tron help and transmit",
    ):
        assert parse_tron_command(utterance) is None


def test_grammar_has_no_transmit_or_callsign_commands() -> None:
    grammar = command_grammar()
    assert grammar[-1] == "[unk]"
    assert len(grammar) == len(set(grammar))
    assert "tron open ft eight" in grammar
    assert "tron help" in grammar
    assert all("transmit" not in phrase and "callsign" not in phrase for phrase in grammar)
