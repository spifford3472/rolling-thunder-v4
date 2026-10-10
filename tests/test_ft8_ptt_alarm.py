"""Safety warning dismissal is distinct from recovered RF authorization."""

from rolling_thunder.ft8.ptt_alarm import FT8PttAlarm


def test_only_voice_cancel_dismisses_alarm_without_restoring_tx() -> None:
    alarm = FT8PttAlarm()
    assert not alarm.active and not alarm.tx_inhibited
    alarm.trigger()
    assert alarm.active and alarm.audible and alarm.tx_inhibited
    alarm.voice_cancel()
    assert not alarm.active and not alarm.audible
    assert alarm.tx_inhibited
    alarm.trigger()
    assert alarm.active and alarm.tx_inhibited
