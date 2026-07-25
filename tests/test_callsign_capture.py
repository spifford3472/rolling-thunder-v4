"""Tests for deterministic mock transcript capture state."""

import pytest

from rolling_thunder.callsign_capture import MockTranscriptController


def test_valid_mock_transcript_becomes_committable() -> None:
    controller = MockTranscriptController(
        transcripts=(("KILO", "INDIA", "FIVE", "VICTOR", "NOVEMBER", "BRAVO"),)
    )

    state = controller.capture_next()

    assert state.pending_callsign == "KI5VNB"
    assert state.voice_state == "READY"
    assert state.commit_state == "READY"
    assert state.last_result == "HEARD KI5VNB"


def test_invalid_mock_transcript_is_not_committable() -> None:
    controller = MockTranscriptController(
        transcripts=(("KILO", "INDIA", "FIVE", "UNKNOWN"),)
    )

    state = controller.capture_next()

    assert state.pending_callsign == ""
    assert state.voice_state == "FAILED"
    assert state.commit_state == "DISABLED"
    assert state.last_result == "VOICE ERROR"


def test_discard_clears_pending_callsign() -> None:
    controller = MockTranscriptController(
        transcripts=(("GOLF", "BRAVO", "NINER", "ZERO", "MIKE", "GOLF", "YANKEE"),)
    )
    controller.capture_next()

    state = controller.discard()

    assert state.pending_callsign == ""
    assert state.voice_state == "READY"
    assert state.commit_state == "DISABLED"
    assert state.last_result == "DISCARDED"


def test_mock_transcripts_cycle() -> None:
    controller = MockTranscriptController(
        transcripts=(
            ("KILO", "INDIA", "FIVE", "VICTOR", "NOVEMBER", "BRAVO"),
            ("GOLF", "BRAVO", "NINER", "ZERO", "MIKE", "GOLF", "YANKEE"),
        )
    )

    assert controller.capture_next().pending_callsign == "KI5VNB"
    assert controller.capture_next().pending_callsign == "GB90MGY"
    assert controller.capture_next().pending_callsign == "KI5VNB"


def test_empty_mock_transcript_sequence_is_rejected() -> None:
    with pytest.raises(ValueError, match="At least one mock transcript"):
        MockTranscriptController(transcripts=())
