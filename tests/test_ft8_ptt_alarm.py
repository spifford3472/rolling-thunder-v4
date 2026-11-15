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


def test_missing_radio_confirmation_resets_partial_unlock_progress() -> None:
    """An interrupted 1-3-1 cannot finish after missing RX confirmation."""
    from rolling_thunder.physical_controls import ControlAction as A

    alarm = FT8PttAlarm()
    alarm.trigger()
    alarm.voice_cancel()
    assert not alarm.unlock_step(A.PANEL_PRIMARY, ft8_screen=True,
                                 radio_confirmed_receive=True)
    assert not alarm.unlock_step(A.PANEL_TERTIARY, ft8_screen=True,
                                 radio_confirmed_receive=False)
    assert not alarm.unlock_step(A.PANEL_TERTIARY, ft8_screen=True,
                                 radio_confirmed_receive=True)
    assert not alarm.unlock_step(A.PANEL_PRIMARY, ft8_screen=True,
                                 radio_confirmed_receive=True)
    assert alarm.tx_inhibited


def test_production_ui_never_asserts_unverified_physical_receive() -> None:
    """Guard real UI source against reintroducing the unsafe constant True."""
    import ast
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1]
              / 'src/rolling_thunder/ui_main.py').read_text(encoding='utf-8')
    module = ast.parse(source)
    handlers = [node for node in ast.walk(module)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == 'handle_ptt_unlock_action']
    assert len(handlers) == 1
    confirmations = []
    for node in ast.walk(handlers[0]):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != 'unlock_step':
            continue
        value = next((item.value for item in node.keywords
                      if item.arg == 'radio_confirmed_receive'), None)
        assert isinstance(value, ast.Constant) and isinstance(value.value, bool)
        confirmations.append((node.func.value, value.value))
    assert len(confirmations) == 2
    assert any(isinstance(owner, ast.Name) and owner.id == 'visual_test' and passed
               for owner, passed in confirmations)
    assert any(isinstance(owner, ast.Name) and owner.id == 'alarm' and not passed
               for owner, passed in confirmations)


def test_acknowledged_real_alarm_stays_inhibited_without_rx_evidence() -> None:
    """Every repeated unlock attempt must fail without physical RX evidence."""
    from rolling_thunder.physical_controls import ControlAction as A

    alarm = FT8PttAlarm()
    alarm.trigger()
    alarm.voice_cancel()
    for _ in range(3):
        for action in (A.PANEL_PRIMARY, A.PANEL_TERTIARY, A.PANEL_PRIMARY):
            assert not alarm.unlock_step(action, ft8_screen=True,
                                         radio_confirmed_receive=False)
            assert alarm.tx_inhibited
    # A second latched uncertain event must not restore authorization.
    alarm.trigger()
    assert alarm.active and alarm.tx_inhibited


def test_real_operator_overlay_explains_no_automatic_unlock() -> None:
    """Operator instructions must not promise a gesture that now fails closed."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1]
              / 'src/rolling_thunder/ui_main.py').read_text(encoding='utf-8')
    assert 'PRESS COMMAND 1, 3, 1 TO OVERRIDE.' in source
    assert 'VISUAL TEST ONLY: COMMAND 1, 3, 1 TO CLEAR TEST' in source


def test_manual_override_requires_acknowledged_complete_sequence() -> None:
    """An operator can explicitly clear a live alarm without fabricated RX proof."""
    from rolling_thunder.physical_controls import ControlAction as A

    alarm = FT8PttAlarm()
    alarm.trigger()
    for action in (A.PANEL_PRIMARY, A.PANEL_TERTIARY, A.PANEL_PRIMARY):
        assert not alarm.unlock_step(action, ft8_screen=True,
                                     radio_confirmed_receive=False,
                                     operator_recovery_override=True)
    assert alarm.tx_inhibited
    alarm.voice_cancel()
    assert not alarm.unlock_step(A.PANEL_PRIMARY, ft8_screen=False,
                                 radio_confirmed_receive=False,
                                 operator_recovery_override=True)
    for action in (A.PANEL_PRIMARY, A.PANEL_TERTIARY):
        assert not alarm.unlock_step(action, ft8_screen=True,
                                     radio_confirmed_receive=False,
                                     operator_recovery_override=True)
    assert alarm.tx_inhibited
    assert alarm.unlock_step(A.PANEL_PRIMARY, ft8_screen=True,
                             radio_confirmed_receive=False,
                             operator_recovery_override=True)
    assert not alarm.active and not alarm.tx_inhibited


def test_restart_creates_new_alarm_with_no_session_lockout() -> None:
    """An unresolved session latch is not persisted across application restart."""
    alarm = FT8PttAlarm()
    alarm.trigger()
    alarm.voice_cancel()
    assert alarm.tx_inhibited
    restarted = FT8PttAlarm()
    assert not restarted.tx_inhibited and not restarted.active


def test_second_fault_rearms_after_manual_override() -> None:
    """Manual recovery cannot permanently disable subsequent failure alarms."""
    from rolling_thunder.physical_controls import ControlAction as A

    alarm = FT8PttAlarm()
    alarm.trigger()
    alarm.voice_cancel()
    for action in (A.PANEL_PRIMARY, A.PANEL_TERTIARY, A.PANEL_PRIMARY):
        alarm.unlock_step(action, ft8_screen=True,
                          radio_confirmed_receive=False,
                          operator_recovery_override=True)
    assert not alarm.tx_inhibited
    alarm.trigger()
    assert alarm.active and alarm.tx_inhibited


def test_ui_operator_override_does_not_claim_verified_receive() -> None:
    """Verify the real override path explicitly retains RX-unverified semantics."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1]
              / 'src/rolling_thunder/ui_main.py').read_text(encoding='utf-8')
    assert 'operator_recovery_override=True' in source
    assert 'radio_confirmed_receive=False' in source
    assert 'physical_rx_verified=false transmit_started=false' in source
