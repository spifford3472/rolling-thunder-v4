"""Mandatory preparation interval for live microphone acceptance."""

from rolling_thunder.tron_acceptance import TronAcceptanceCountdown


def test_microphone_cannot_start_before_full_thirty_seconds() -> None:
    countdown = TronAcceptanceCountdown(duration_seconds=30)
    countdown.start(generation=7)

    assert countdown.remaining(100.0, 7) == 30
    assert countdown.remaining(129.999, 7) == 1
    assert countdown.remaining(130.0, 7) == 0
    assert countdown.remaining(131.0, 7) is None


def test_callsign_preemption_cancels_preparation() -> None:
    countdown = TronAcceptanceCountdown()
    countdown.start(generation=3)

    assert countdown.remaining(10.0, generation=4) == -1
    assert not countdown.active


def test_operator_can_cancel_preparation() -> None:
    countdown = TronAcceptanceCountdown()
    countdown.start(generation=0)
    assert countdown.cancel()
    assert countdown.remaining(30.0, generation=0) is None
    assert not countdown.cancel()
