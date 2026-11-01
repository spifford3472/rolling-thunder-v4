"""Physical callsign priority and exclusive microphone ownership tests."""

from rolling_thunder.tron_audio_gate import TronAudioGate


def test_tron_never_overlaps_callsign() -> None:
    gate = TronAudioGate()
    assert gate.begin_tron()
    assert not gate.begin_tron()
    assert not gate.begin_callsign()
    assert gate.request_callsign() is False
    assert not gate.begin_tron()
    assert not gate.begin_callsign()
    assert gate.release("tron")
    assert gate.begin_callsign()
    assert not gate.begin_tron()
    assert not gate.release("tron")
    assert gate.release("callsign")
    assert gate.begin_tron()


def test_callsign_request_blocks_tron_until_cancelled() -> None:
    gate = TronAudioGate()
    assert gate.request_callsign()
    assert not gate.begin_tron()
    gate.cancel_callsign_request()
    assert not gate.begin_callsign()
    assert gate.begin_tron()


def test_unowned_release_is_rejected() -> None:
    gate = TronAudioGate()
    assert not gate.release("tron")
    assert not gate.release("callsign")
    assert gate.owner is None
