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


def test_unlock_requires_ft8_screen_verified_receive_and_131() -> None:
    from rolling_thunder.physical_controls import ControlAction

    alarm = FT8PttAlarm()
    alarm.trigger()
    seq = (ControlAction.PANEL_PRIMARY, ControlAction.PANEL_TERTIARY,
           ControlAction.PANEL_PRIMARY)
    for action in seq:
        assert not alarm.unlock_step(action, ft8_screen=True, radio_confirmed_receive=True)
    alarm.voice_cancel()
    assert not alarm.unlock_step(seq[0], ft8_screen=False, radio_confirmed_receive=True)
    assert not alarm.unlock_step(seq[0], ft8_screen=True, radio_confirmed_receive=False)
    assert not alarm.unlock_step(seq[0], ft8_screen=True, radio_confirmed_receive=True)
    assert not alarm.unlock_step(seq[1], ft8_screen=True, radio_confirmed_receive=True)
    assert alarm.unlock_step(seq[2], ft8_screen=True, radio_confirmed_receive=True)
    assert not alarm.tx_inhibited


def test_wrong_order_resets_unlock_sequence() -> None:
    from rolling_thunder.physical_controls import ControlAction as A

    alarm = FT8PttAlarm()
    alarm.trigger()
    alarm.voice_cancel()
    assert not alarm.unlock_step(A.PANEL_PRIMARY, ft8_screen=True, radio_confirmed_receive=True)
    assert not alarm.unlock_step(A.PANEL_PRIMARY, ft8_screen=True, radio_confirmed_receive=True)
    assert not alarm.unlock_step(A.PANEL_TERTIARY, ft8_screen=True, radio_confirmed_receive=True)
    assert alarm.unlock_step(A.PANEL_PRIMARY, ft8_screen=True, radio_confirmed_receive=True)
