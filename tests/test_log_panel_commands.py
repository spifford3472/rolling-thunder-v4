"""Tests for LOG-specific active-panel command routing."""

from rolling_thunder.context_navigation import ContextId, ContextNavigationController
from rolling_thunder.log_panel_commands import LogAwareActivePanelCommands


class DelegateCommands:
    def __init__(self) -> None:
        self.primary_calls = 0

    def activate_context(self, context_id: ContextId) -> None:
        del context_id

    def primary(self) -> bool:
        self.primary_calls += 1
        return True

    def secondary(self) -> bool:
        return False

    def tertiary(self) -> bool:
        return False

    def tertiary_long(self) -> bool:
        return False

    def move_previous(self) -> bool:
        return False

    def move_next(self) -> bool:
        return False

    def activate_selection(self) -> bool:
        return False

    def back(self) -> bool:
        return False

    def synchronize_radio_state(self) -> bool:
        return False


class RecordingLogSync:
    def __init__(self) -> None:
        self.calls = 0

    def request_sync(self) -> bool:
        self.calls += 1
        return True


def test_context_button_one_requests_log_sync_only_in_log_context() -> None:
    navigation = ContextNavigationController(ContextId.LOG)
    delegate = DelegateCommands()
    log_sync = RecordingLogSync()
    commands = LogAwareActivePanelCommands(navigation, delegate, log_sync)

    assert commands.primary() is True
    assert log_sync.calls == 1
    assert delegate.primary_calls == 0

    navigation.select(ContextId.POTA)
    assert commands.primary() is True
    assert log_sync.calls == 1
    assert delegate.primary_calls == 1


def test_other_log_controls_preserve_existing_delegate_behavior() -> None:
    navigation = ContextNavigationController(ContextId.LOG)
    delegate = DelegateCommands()
    commands = LogAwareActivePanelCommands(navigation, delegate, RecordingLogSync())

    assert commands.secondary() is False
    assert commands.tertiary() is False
    assert commands.tertiary_long() is False
    assert commands.move_previous() is False
    assert commands.move_next() is False
    assert commands.activate_selection() is False
    assert commands.back() is False
