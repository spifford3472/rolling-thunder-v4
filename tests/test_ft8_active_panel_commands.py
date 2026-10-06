"""Tests for FT8-aware active-panel command routing."""

from rolling_thunder.context_navigation import ContextId, ContextNavigationController
from rolling_thunder.ft8.domain import (
    FT8IncomingCall,
    FT8MessageKind,
    FT8Period,
    FT8QsoState,
)
from rolling_thunder.ft8.panel import FT8PanelMode, FT8PanelSnapshot
from rolling_thunder.ft8_active_panel_commands import FT8AwareActivePanelCommands


class Delegate:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def activate_context(self, context_id: ContextId) -> None:
        self.calls.append(f"activate:{context_id}")

    def primary(self) -> bool:
        self.calls.append("primary")
        return True

    def secondary(self) -> bool:
        self.calls.append("secondary")
        return True

    def tertiary(self) -> bool:
        self.calls.append("tertiary")
        return True

    def tertiary_long(self) -> bool:
        self.calls.append("tertiary_long")
        return True

    def move_previous(self) -> bool:
        self.calls.append("move_previous")
        return True

    def move_next(self) -> bool:
        self.calls.append("move_next")
        return True

    def activate_selection(self) -> bool:
        self.calls.append("activate_selection")
        return True

    def back(self) -> bool:
        self.calls.append("back")
        return True

    def synchronize_radio_state(self) -> bool:
        self.calls.append("sync")
        return True


class Panel:
    def __init__(self) -> None:
        self.mode = FT8PanelMode.BROWSE
        self.selected_callsign: str | None = None
        self.calls: list[str] = []
        self.incoming_call: FT8IncomingCall | None = None

    def snapshot(self) -> FT8PanelSnapshot:
        state = FT8QsoState.IDLE if self.mode is FT8PanelMode.BROWSE else FT8QsoState.WAIT_REPORT
        if self.mode is FT8PanelMode.TERMINAL:
            state = FT8QsoState.ABORTED
        return FT8PanelSnapshot(
            mode=self.mode,
            cq_activity=(),
            qso_state=state,
            incoming_call=self.incoming_call,
        )

    def select_previous(self) -> str | None:
        self.calls.append("previous")
        self.selected_callsign = "K1ABC"
        return self.selected_callsign

    def select_next(self) -> str | None:
        self.calls.append("next")
        self.selected_callsign = "W1XYZ"
        return self.selected_callsign

    def clear_selection(self) -> bool:
        self.calls.append("clear")
        changed = self.selected_callsign is not None
        self.selected_callsign = None
        return changed

    def activate_selection(self) -> bool:
        self.calls.append("activate")
        return self.selected_callsign is not None

    def answer_incoming_call(self) -> bool:
        self.calls.append("answer")
        return self.incoming_call is not None

    def dismiss_incoming_call(self) -> bool:
        self.calls.append("ignore")
        return self.incoming_call is not None

    def abort(self) -> None:
        self.calls.append("abort")

    def return_to_browser(self) -> object | None:
        self.calls.append("return")
        return object()


def test_ft8_context_owns_selection_and_activation_without_delegate() -> None:
    navigation = ContextNavigationController(ContextId.FT8)
    delegate = Delegate()
    panel = Panel()
    commands = FT8AwareActivePanelCommands(navigation, delegate, panel)

    assert commands.move_next() is True
    assert commands.activate_selection() is True
    assert panel.calls == ["next", "activate"]
    assert delegate.calls == []



class PendingCallsign:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def preload_callsign(self, callsign: str) -> bool:
        self.calls.append(callsign)
        return True

    def discard(self) -> object:
        self.calls.append("discard")
        return object()


def test_ft8_selection_preloads_dashboard_callsign() -> None:
    navigation = ContextNavigationController(ContextId.FT8)
    delegate = Delegate()
    panel = Panel()
    pending = PendingCallsign()
    commands = FT8AwareActivePanelCommands(
        navigation,
        delegate,
        panel,
        pending_callsign=pending,
    )

    assert commands.move_next() is True
    assert pending.calls == ["W1XYZ"]

    assert commands.move_previous() is True
    assert pending.calls == ["W1XYZ", "K1ABC"]


def test_ft8_context_button_1_cycles_band_only_in_browser() -> None:
    navigation = ContextNavigationController(ContextId.FT8)
    delegate = Delegate()
    panel = Panel()
    band_calls: list[str] = []
    commands = FT8AwareActivePanelCommands(
        navigation,
        delegate,
        panel,
        cycle_band=lambda: band_calls.append("cycle") is None,
    )

    assert commands.primary() is True
    assert band_calls == ["cycle"]

    panel.mode = FT8PanelMode.ACTIVE
    assert commands.primary() is False
    assert band_calls == ["cycle"]
    assert delegate.calls == []


def test_ft8_incoming_call_uses_button_2_answer_and_button_3_ignore() -> None:
    navigation = ContextNavigationController(ContextId.FT8)
    panel = Panel()
    panel.incoming_call = FT8IncomingCall(
        callsign="K1ABC",
        period=FT8Period(100),
        snr_db=-8,
        dt_seconds=0.1,
        audio_frequency_hz=1500,
        kind=FT8MessageKind.REPORT,
        grid="FN31",
        report_db=-8,
    )
    commands = FT8AwareActivePanelCommands(navigation, Delegate(), panel)

    assert commands.secondary() is True
    assert commands.tertiary() is True
    assert panel.calls == ["answer", "ignore"]


def test_ft8_band_change_clears_selection_and_dashboard_callsign() -> None:
    navigation = ContextNavigationController(ContextId.FT8)
    delegate = Delegate()
    panel = Panel()
    panel.selected_callsign = "K1ABC"
    pending = PendingCallsign()
    commands = FT8AwareActivePanelCommands(
        navigation,
        delegate,
        panel,
        cycle_band=lambda: True,
        pending_callsign=pending,
    )

    assert commands.primary() is True

    assert panel.selected_callsign is None
    assert "clear" in panel.calls
    assert pending.calls == ["discard"]


def test_ft8_context_button_3_short_aborts_only_active_qso() -> None:
    navigation = ContextNavigationController(ContextId.FT8)
    delegate = Delegate()
    panel = Panel()
    commands = FT8AwareActivePanelCommands(navigation, delegate, panel)

    assert commands.tertiary() is False
    assert panel.calls == []

    panel.mode = FT8PanelMode.ACTIVE
    assert commands.tertiary() is True
    assert panel.calls == ["abort"]

    panel.mode = FT8PanelMode.TERMINAL
    assert commands.tertiary() is True
    assert panel.calls == ["abort", "return"]
    assert delegate.calls == []


def test_ft8_terminal_encoder_press_returns_to_browser() -> None:
    navigation = ContextNavigationController(ContextId.FT8)
    delegate = Delegate()
    panel = Panel()
    panel.mode = FT8PanelMode.TERMINAL
    commands = FT8AwareActivePanelCommands(navigation, delegate, panel)

    assert commands.activate_selection() is True
    assert panel.calls == ["return"]
    assert delegate.calls == []


def test_ft8_terminal_context_button_3_returns_to_browser() -> None:
    navigation = ContextNavigationController(ContextId.FT8)
    delegate = Delegate()
    panel = Panel()
    panel.mode = FT8PanelMode.TERMINAL
    commands = FT8AwareActivePanelCommands(navigation, delegate, panel)

    assert commands.tertiary() is True
    assert panel.calls == ["return"]
    assert delegate.calls == []


def test_ft8_back_aborts_active_qso_and_acknowledges_terminal_result() -> None:
    navigation = ContextNavigationController(ContextId.FT8)
    delegate = Delegate()
    panel = Panel()
    commands = FT8AwareActivePanelCommands(navigation, delegate, panel)

    panel.mode = FT8PanelMode.ACTIVE
    assert commands.back() is True
    panel.mode = FT8PanelMode.TERMINAL
    assert commands.back() is True

    assert panel.calls == ["abort", "return"]
    assert delegate.calls == []


def test_entering_and_leaving_ft8_context_apply_receive_lifecycle() -> None:
    navigation = ContextNavigationController(ContextId.BROWSE)
    delegate = Delegate()
    panel = Panel()
    enters: list[str] = []
    exits: list[str] = []
    commands = FT8AwareActivePanelCommands(
        navigation,
        delegate,
        panel,
        enter_ft8=lambda: enters.append("enter") is None,
        exit_ft8=lambda: exits.append("exit") is None,
    )

    navigation.select(ContextId.FT8)
    commands.activate_context(ContextId.FT8)
    assert enters == ["enter"]
    assert exits == []

    navigation.select(ContextId.POTA)
    commands.activate_context(ContextId.POTA)
    assert enters == ["enter"]
    assert exits == ["exit"]


def test_leaving_ft8_context_requests_restore_once() -> None:
    navigation = ContextNavigationController(ContextId.FT8)
    delegate = Delegate()
    panel = Panel()
    exits: list[str] = []
    commands = FT8AwareActivePanelCommands(
        navigation,
        delegate,
        panel,
        exit_ft8=lambda: exits.append("exit") is None,
    )

    commands.activate_context(ContextId.FT8)
    assert exits == []

    commands.activate_context(ContextId.REPEATERS)
    assert exits == ["exit"]

    commands.activate_context(ContextId.AI)
    assert exits == ["exit"]


def test_context_button_3_short_and_long_abort_active_qso() -> None:
    navigation = ContextNavigationController(ContextId.FT8)
    delegate = Delegate()
    panel = Panel()
    commands = FT8AwareActivePanelCommands(navigation, delegate, panel)

    panel.mode = FT8PanelMode.ACTIVE
    assert commands.tertiary() is True
    assert commands.tertiary_long() is True

    assert panel.calls == ["abort", "abort"]
    assert delegate.calls == []


def test_context_button_3_is_inert_in_ft8_when_no_qso_is_active() -> None:
    navigation = ContextNavigationController(ContextId.FT8)
    delegate = Delegate()
    panel = Panel()
    commands = FT8AwareActivePanelCommands(navigation, delegate, panel)

    panel.mode = FT8PanelMode.BROWSE
    assert commands.tertiary() is False
    assert commands.tertiary_long() is False

    assert panel.calls == []
    assert delegate.calls == []



def test_ft8_context_button_3_aborts_active_qso_only() -> None:
    navigation = ContextNavigationController(ContextId.FT8)
    delegate = Delegate()
    panel = Panel()
    commands = FT8AwareActivePanelCommands(navigation, delegate, panel)

    assert commands.tertiary() is False
    panel.mode = FT8PanelMode.ACTIVE
    assert commands.tertiary() is True

    assert panel.calls == ["abort"]
    assert delegate.calls == []


def test_non_ft8_context_preserves_delegate_behavior() -> None:
    navigation = ContextNavigationController(ContextId.POTA)
    delegate = Delegate()
    panel = Panel()
    commands = FT8AwareActivePanelCommands(navigation, delegate, panel)

    assert commands.move_next() is True
    assert commands.activate_selection() is True
    assert commands.back() is True

    assert delegate.calls == ["move_next", "activate_selection", "back"]
    assert panel.calls == []


def test_selecting_new_ft8_station_clears_stale_start_status() -> None:
    navigation = ContextNavigationController(ContextId.FT8)
    delegate = Delegate()
    panel = Panel()
    resets: list[str] = []
    commands = FT8AwareActivePanelCommands(
        navigation,
        delegate,
        panel,
        clear_start_status=lambda: resets.append("reset") is None,
    )

    assert commands.move_next() is True
    assert resets == ["reset"]

    assert commands.move_previous() is True
    assert resets == ["reset", "reset"]
